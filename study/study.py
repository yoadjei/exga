"""run the user study's paperwork and analysis (spec 11.3, ADR 0012); see study/README.md.

    python study/study.py prepare --participants 8           # assignment and blank forms
    python study/study.py sheet --papers study/papers/A --out study/data/sheet_A.csv
    python study/study.py calibration --records <records/hosted.jsonl>   # without study papers
    python study/study.py analyse                            # tables and a manifest

exit codes: 0 success, 2 a missing or malformed input, or a form that already exists.
"""

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from exga import study
from exga.errors import ConfigError
from exga.fields import load_fields
from exga.gold import load_gold
from exga.manifest import build_manifest
from exga.papers import load_folder
from exga.records import load_records, save_records
from exga.schemas import Document, FieldSpec
from exga.settings import DocumentSettings, MatchingSettings, load_settings
from exga.tables import write_rows

REPOSITORY = Path(__file__).resolve().parents[1]
DATA = Path("study/data")
PAPERS = Path("study/papers")
FIELDS = Path("data/annotated/fields.yaml")
GOLD = Path("data/annotated/gold.csv")
RESULTS = Path("results/study")
EXIT_CONFIG = 2
FORMS = ("assignment.csv", "sessions.csv", "questionnaire.csv")
ANSWERS = "answers"
app = typer.Typer(no_args_is_help=True, add_completion=False)
EnvFile = Annotated[Path | None, typer.Option(help="Settings file (.env format).")]


@app.command()
def prepare(
    participants: Annotated[int, typer.Option(help="How many people take part.")],
    seed: Annotated[int, typer.Option(help="Seed of the counterbalanced order.")] = 0,
    out: Annotated[Path, typer.Option(help="Folder for the forms.")] = DATA,
) -> None:
    """Write the assignment and the blank session and questionnaire forms."""
    existing = [name for name in FORMS if (out / name).exists()]
    if existing:
        _fail(
            f"{out / existing[0]} already exists; it may hold collected data. Delete the forms "
            "yourself if you mean to start again."
        )
    try:
        assignments = study.assign(participants, seed)
    except ValueError as exc:
        _fail(str(exc))
    write_rows(study.assignment_rows(assignments), out / FORMS[0], spreadsheet=True)
    write_rows(study.session_rows(assignments), out / FORMS[1], spreadsheet=True)
    write_rows(study.questionnaire_rows(assignments), out / FORMS[2], spreadsheet=True)
    (out / ANSWERS).mkdir(exist_ok=True)
    typer.echo(
        f"Wrote forms for {participants} participants (seed {seed}) to {out}. Save each "
        f"participant's sheet as {ANSWERS}/<id>_manual.csv and their exga export as "
        f"{ANSWERS}/<id>_tool.csv."
    )


@app.command()
def sheet(
    papers: Annotated[Path, typer.Option(help="Folder of one paper set.")],
    out: Annotated[Path, typer.Option(help="The blank sheet to write (CSV).")],
    fields: Annotated[Path, typer.Option(help="Field list (YAML).")] = FIELDS,
    env_file: EnvFile = None,
) -> None:
    """Write the blank sheet a participant fills in by hand for one paper set."""
    if out.exists():
        _fail(f"{out} already exists; delete it yourself to write a new one.")
    try:
        settings = load_settings(env_file)
        specs = load_fields(fields)
        documents = _paper_set(papers, settings.document)
    except ConfigError as exc:
        _fail(str(exc))
    rows: list[dict[str, object]] = [
        {
            "paper": document.filename,
            "field": spec.name,
            "question": spec.description,
            "value": None,
        }
        for document in documents
        for spec in specs
    ]
    write_rows(rows, out, spreadsheet=True)
    typer.echo(f"Wrote {len(rows)} questions about {len(documents)} papers to {out}.")


@app.command()
def calibration(
    records: Annotated[Path, typer.Option(help="Records file from the annotated experiment.")],
    papers: Annotated[Path, typer.Option(help="Folder holding the A and B paper sets.")] = PAPERS,
    out: Annotated[Path, typer.Option(help="The records file to import.")] = DATA
    / "calibration.jsonl",
    env_file: EnvFile = None,
) -> None:
    """Copy a records file without the study papers, so the tool is not calibrated on them."""
    try:
        settings = load_settings(env_file)
        study_papers = {
            document.paper_id
            for paper_set in study.PAPER_SETS
            for document in _paper_set(papers / paper_set, settings.document)
        }
        loaded = load_records(records)
    except ConfigError as exc:
        _fail(str(exc))
    kept = [record for record in loaded if record.paper_id not in study_papers]
    save_records(kept, out)
    typer.echo(
        f"Wrote {len(kept)} records to {out}; left out {len(loaded) - len(kept)} of "
        f"{len(loaded)} records, those of the {len(study_papers)} study papers."
    )


@app.command()
def analyse(
    data: Annotated[Path, typer.Option(help="Folder of the filled-in forms.")] = DATA,
    papers: Annotated[Path, typer.Option(help="Folder holding the A and B paper sets.")] = PAPERS,
    fields: Annotated[Path, typer.Option(help="Field list (YAML).")] = FIELDS,
    gold: Annotated[Path, typer.Option(help="Gold file of the study papers.")] = GOLD,
    out: Annotated[Path, typer.Option(help="Folder for the tables.")] = RESULTS,
    env_file: EnvFile = None,
) -> None:
    """Score every participant who finished and summarise time, accuracy, SUS and trust."""
    try:
        settings = load_settings(env_file)
        specs = load_fields(fields)
        set_gold = _set_gold(papers, specs, load_gold(gold, specs), settings.document)
        assignments = study.read_assignments(_read(data / FORMS[0]))
        minutes = study.read_minutes(_read(data / FORMS[1]))
        responses = study.read_questionnaire(_read(data / FORMS[2]))
        results, excluded = [], {}
        for assignment in assignments:
            outcome = _participant(
                assignment, minutes, responses, data / ANSWERS, set_gold, specs, settings.matching
            )
            if isinstance(outcome, str):
                excluded[assignment.participant] = outcome
            else:
                results.append(outcome)
    except ConfigError as exc:
        _fail(str(exc))
    write_rows([result.row() for result in results], out / "participants.csv")
    write_rows(study.summary_rows(results), out / "summary.csv")
    write_rows(study.trust_rows(results), out / "trust.csv")
    manifest = build_manifest(
        config={
            name: path.as_posix()
            for name, path in (("data", data), ("papers", papers), ("fields", fields))
        },
        settings=settings,
        inputs={
            "fields": fields,
            "gold": gold,
            **{name: data / name for name in FORMS},
            **{f"answers/{path.name}": path for path in sorted((data / ANSWERS).glob("*.csv"))},
        },
        extra={"participants": len(results), "excluded": excluded},
        repo=REPOSITORY,
        at=datetime.now(UTC),
    )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"Summarised {len(results)} participants in {out}.")
    for participant, reason in excluded.items():
        typer.echo(f"Left out {participant}: {reason}.")


def _participant(
    assignment: study.Assignment,
    minutes: dict[tuple[str, study.Condition], float],
    responses: dict[str, study.Responses],
    answers: Path,
    set_gold: dict[study.PaperSet, study.Answers],
    specs: tuple[FieldSpec, ...],
    rules: MatchingSettings,
) -> study.ParticipantResult | str:
    """the participant's result, or why they cannot be scored yet."""
    participant = assignment.participant
    for condition in study.CONDITIONS:
        if (participant, condition) not in minutes:
            return f"no time recorded for the {condition} condition"
    files = {
        condition: answers / f"{participant}_{condition}.csv" for condition in study.CONDITIONS
    }
    for condition, path in files.items():
        if not path.is_file():
            return f"no answers for the {condition} condition ({path.name})"
    if participant not in responses:
        return "the questionnaire is not complete"
    by_name = {spec.name: spec for spec in specs}

    def session(condition: study.Condition, given: study.Answers) -> study.Session:
        expected = set_gold[assignment.paper_set(condition)]
        return study.Session(
            minutes[participant, condition], study.accuracy(given, expected, by_name, rules)
        )

    tool_rows = _read(files["tool"])
    return study.ParticipantResult(
        assignment=assignment,
        manual=session("manual", study.sheet_answers(_read(files["manual"]))),
        tool=session("tool", study.export_answers(tool_rows)),
        checked=study.checked_items(tool_rows),
        responses=responses[participant],
    )


def _set_gold(
    papers: Path,
    specs: tuple[FieldSpec, ...],
    gold: dict[tuple[str, str], str | None],
    settings: DocumentSettings,
) -> dict[study.PaperSet, study.Answers]:
    """each paper set's gold values keyed by (file name, field); every item must have one."""
    by_set: dict[study.PaperSet, study.Answers] = {}
    for paper_set in study.PAPER_SETS:
        values: study.Answers = {}
        for document in _paper_set(papers / paper_set, settings):
            for spec in specs:
                if (document.paper_id, spec.name) not in gold:
                    raise ConfigError(
                        f"the gold file has no {spec.name} for {document.filename}; every study "
                        "item needs a gold value"
                    )
                values[document.filename, spec.name] = gold[document.paper_id, spec.name]
        by_set[paper_set] = values
    return by_set


def _paper_set(folder: Path, settings: DocumentSettings) -> list[Document]:
    documents, skipped = load_folder(folder, settings)
    if skipped:
        raise ConfigError(
            f"{folder}: {skipped[0].filename} cannot be read ({skipped[0].reason}); study "
            "papers must be text PDFs"
        )
    return documents


def _read(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc


def _fail(message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(EXIT_CONFIG)


if __name__ == "__main__":
    app()
