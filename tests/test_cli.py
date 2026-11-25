import csv
import json
import os
import shutil
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from exga import cli
from exga.llm.hosted import HostedLLMClient
from exga.llm.limits import RateLimiter
from exga.schemas import FieldSamples
from exga.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE_FIELDS = Path(__file__).parents[1] / "examples" / "fields.yaml"
ANSWER = json.dumps({"value": "120", "evidence": "A total of 120 participants", "page": 1})


@pytest.fixture(autouse=True)
def _isolate_from_developer_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [name for name in os.environ if name.upper().startswith("EXGA_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("EXGA_HOSTED__MODEL", "test-model")


def chat_completion(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    choices = [
        {"index": i, "message": {"role": "assistant", "content": ANSWER}} for i in range(body["n"])
    ]
    usage = {"prompt_tokens": 100, "completion_tokens": 20 * body["n"]}
    return httpx.Response(200, json={"choices": choices, "usage": usage})


@pytest.fixture
def offline_model(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    requests: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(1)
        return chat_completion(request)

    def build(settings: Settings) -> HostedLLMClient:
        return HostedLLMClient(
            settings.hosted,
            transport=httpx.MockTransport(handler),
            limiter=RateLimiter(1e9, 1000),
        )

    monkeypatch.setattr(cli, "build_client", build)
    return requests


@pytest.fixture
def papers(tmp_path: Path) -> Path:
    folder = tmp_path / "papers"
    folder.mkdir()
    shutil.copy(FIXTURES / "trial_report.pdf", folder / "trial.pdf")
    shutil.copy(FIXTURES / "encrypted.pdf", folder / "locked.pdf")
    return folder


def run(*args: str) -> tuple[int, str, str]:
    result = CliRunner().invoke(cli.app, list(args))
    return result.exit_code, result.stdout, result.stderr


def test_extract_writes_samples_and_a_run_summary(
    tmp_path: Path, papers: Path, offline_model: list[int]
) -> None:
    out = tmp_path / "run"

    code, stdout, stderr = run(
        "extract", "--papers", str(papers), "--fields", str(EXAMPLE_FIELDS),
        "--out", str(out), "--cache", str(tmp_path / "cache"),
    )  # fmt: skip

    assert code == 0, stderr
    items = [
        FieldSamples.model_validate_json(line)
        for line in (out / "samples.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [item.field for item in items][:2] == ["sample_size", "year"]
    summary = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert (summary["papers"], summary["items"]) == (1, 6)
    assert summary["skipped"][0]["file"] == "locked.pdf"
    assert summary["requests_sent"] == len(offline_model)
    assert summary["usage"]["requests"] == len(offline_model)
    assert "Paper text is sent to https://api.openai.com/v1 for model test-model." in stdout
    assert "skipped locked.pdf" in stderr


def test_a_second_run_is_answered_from_the_cache(
    tmp_path: Path, papers: Path, offline_model: list[int]
) -> None:
    args = ["extract", "--papers", str(papers), "--fields", str(EXAMPLE_FIELDS)]
    cache = ["--cache", str(tmp_path / "cache")]
    run(*args, "--out", str(tmp_path / "first"), *cache)
    sent = len(offline_model)

    code, _, _ = run(*args, "--out", str(tmp_path / "second"), *cache)

    assert code == 0
    assert len(offline_model) == sent
    summary = json.loads((tmp_path / "second" / "run.json").read_text(encoding="utf-8"))
    assert summary["requests_sent"] == 0


def test_a_missing_model_name_is_a_configuration_error(
    tmp_path: Path, papers: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EXGA_HOSTED__MODEL")

    code, _, stderr = run(
        "extract", "--papers", str(papers), "--fields", str(EXAMPLE_FIELDS),
        "--out", str(tmp_path / "run"),
    )  # fmt: skip

    assert code == cli.EXIT_CONFIG
    assert "hosted.model is not set" in stderr


@pytest.mark.usefixtures("offline_model")
def test_a_spent_budget_stops_the_run_with_its_own_exit_code(
    tmp_path: Path, papers: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EXGA_HOSTED__INPUT_PRICE_PER_MILLION", "1000000")
    monkeypatch.setenv("EXGA_HOSTED__OUTPUT_PRICE_PER_MILLION", "0")
    monkeypatch.setenv("EXGA_HOSTED__BUDGET_USD", "50")

    code, _, stderr = run(
        "extract", "--papers", str(papers), "--fields", str(EXAMPLE_FIELDS),
        "--out", str(tmp_path / "run"), "--cache", str(tmp_path / "cache"),
    )  # fmt: skip

    assert code == cli.EXIT_BUDGET
    assert "Rerun to continue" in stderr
    assert not (tmp_path / "run" / "samples.jsonl").exists()


def test_the_annotation_sheet_lists_every_paper_and_field(tmp_path: Path, papers: Path) -> None:
    out = tmp_path / "sheet"

    code, stdout, _ = run(
        "annotation-sheet", "--papers", str(papers), "--fields", str(EXAMPLE_FIELDS),
        "--out", str(out),
    )  # fmt: skip

    assert code == 0
    with (out / "gold_template.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 6
    assert {row["file"] for row in rows} == {"trial.pdf"}
    assert {row["double_annotate"] for row in rows} == {"yes"}
    assert "1 papers (seed 0) are marked for a second annotator" in stdout


def gold_file(path: Path, paper_id: str, size: str, design: str) -> Path:
    path.write_text(
        f"paper_id,field,value\n{paper_id},sample_size,{size}\n{paper_id},study_design,{design}\n",
        encoding="utf-8",
    )
    return path


def test_check_gold_reports_counts_and_agreement(tmp_path: Path) -> None:
    paper_id = "a" * 64
    first = gold_file(tmp_path / "first.csv", paper_id, "120", "rct")
    second = gold_file(tmp_path / "second.csv", paper_id, "120", "cohort")

    code, stdout, _ = run(
        "check-gold", "--gold", str(first), "--fields", str(EXAMPLE_FIELDS),
        "--second", str(second),
    )  # fmt: skip

    assert code == 0
    assert "first.csv is valid: 2 values for 1 papers." in stdout
    assert "sample_size: 100% (1 of 1)" in stdout
    assert "study_design: 0% (0 of 1)" in stdout
    assert "country: no shared items" in stdout


def test_check_gold_rejects_a_malformed_file(tmp_path: Path) -> None:
    bad = gold_file(tmp_path / "bad.csv", "a" * 64, "lots", "rct")

    code, _, stderr = run("check-gold", "--gold", str(bad), "--fields", str(EXAMPLE_FIELDS))

    assert code == cli.EXIT_CONFIG
    assert "line 2" in stderr
