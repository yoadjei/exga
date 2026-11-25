import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pydantic import SecretStr

from exga.manifest import build_manifest, content_hash, file_sha256, git_state
from exga.settings import HostedSettings, Settings

NOW = datetime(2026, 11, 25, tzinfo=UTC)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_the_content_hash_ignores_key_order() -> None:
    assert content_hash({"a": 1, "b": [1, 2]}) == content_hash({"b": [1, 2], "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_a_file_hash_is_its_sha256(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_bytes(b"abc")

    assert file_sha256(tmp_path / "x.txt") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_git_state_names_the_commit_and_whether_the_tree_changed(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    git(
        tmp_path,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
    )
    clean = git_state(tmp_path)
    (tmp_path / "new.txt").write_text("changed", encoding="utf-8")
    dirty = git_state(tmp_path)

    assert clean.commit is not None
    assert len(clean.commit) == 40
    assert (clean.dirty, dirty.dirty) == (False, True)


def test_outside_a_repository_the_git_state_is_unknown(tmp_path: Path) -> None:
    state = git_state(tmp_path / "missing")

    assert (state.commit, state.dirty) == (None, None)


def test_a_manifest_records_inputs_and_versions_but_never_the_api_key(tmp_path: Path) -> None:
    (tmp_path / "samples.jsonl").write_bytes(b"{}\n")
    settings = Settings(hosted=HostedSettings(model="m", api_key=SecretStr("sk-secret-123")))

    manifest = build_manifest(
        config={"name": "main"},
        settings=settings,
        inputs={"samples": tmp_path / "samples.jsonl"},
        extra={"seeds": [0, 1]},
        repo=tmp_path,
        at=NOW,
    )

    text = json.dumps(manifest)
    assert "sk-secret-123" not in text
    assert "api_key" not in text
    assert manifest["config_hash"] == content_hash({"name": "main"})
    assert manifest["inputs"] == {
        "samples": {
            "path": str(tmp_path / "samples.jsonl"),
            "sha256": file_sha256(tmp_path / "samples.jsonl"),
        }
    }
    assert manifest["seeds"] == [0, 1]
    assert manifest["created_at"] == NOW.isoformat()
    packages = manifest["packages"]
    assert isinstance(packages, dict)
    assert set(packages) >= {"exga", "numpy", "scipy", "pydantic"}
