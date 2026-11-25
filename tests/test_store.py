import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from exga.document import text_document
from exga.errors import ConfigError
from exga.schemas import CalibrationRecord, Extraction, FieldSpec, Signals, ThresholdResult
from exga.store import MIGRATIONS, ProjectStore

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 26, 9, 30, tzinfo=UTC)
SPECS = (
    FieldSpec(name="sample_size", description="participants", group="numeric"),
    FieldSpec(name="country", description="country", group="short_text"),
)
PAPER = text_document("A total of 120 participants in Ghana.", "a.md")


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    return ProjectStore(tmp_path / "project.sqlite")


def extraction(
    field: str, value: str | None, score: float, decision: str | None = None
) -> Extraction:
    return Extraction(
        paper_id=PAPER.paper_id,
        field=field,
        samples=(),
        value=value,
        evidence=None,
        signals=Signals(agreement=score),
        score=score,
        decision=decision,  # type: ignore[arg-type]
        model_id="mock",
        prompt_version="extract_v1",
    )


def record(wrong: bool, score: float = 0.9) -> CalibrationRecord:
    return CalibrationRecord(
        paper_id=PAPER.paper_id,
        field="sample_size",
        group="numeric",
        score=score,
        wrong=wrong,
        source="random_audit",
        created_at=NOW,
    )


def test_a_new_store_applies_every_migration(store: ProjectStore) -> None:
    assert store.schema_version() == len(list(MIGRATIONS.glob("*.sql")))


def test_reopening_a_store_keeps_its_data_and_version(store: ProjectStore) -> None:
    store.save_fields(SPECS)

    reopened = ProjectStore(store.path)

    assert reopened.fields() == SPECS
    assert reopened.schema_version() == store.schema_version()


def test_papers_are_recorded_once_and_keep_their_latest_location(store: ProjectStore) -> None:
    store.add_paper(PAPER, Path("old/a.md"), NOW)
    store.add_paper(PAPER, Path("new/a.md"), LATER)

    [paper] = store.papers()
    assert (paper.paper_id, paper.filename, paper.source, paper.path) == (
        PAPER.paper_id,
        "a.md",
        "text",
        Path("new/a.md"),
    )


def test_extractions_are_replaced_per_paper_and_field(store: ProjectStore) -> None:
    store.add_paper(PAPER, None, NOW)
    store.save_extractions(
        [extraction("sample_size", "120", 0.5), extraction("country", None, 0.4)], NOW
    )

    store.save_extractions([extraction("sample_size", "120", 0.9, "ACCEPT")], LATER)

    by_field = {e.field: e for e in store.extractions()}
    assert (by_field["sample_size"].score, by_field["sample_size"].decision) == (0.9, "ACCEPT")
    assert by_field["country"].value is None


def test_an_extraction_needs_a_known_paper(store: ProjectStore) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        store.save_extractions([extraction("sample_size", "120", 0.5)], NOW)


def test_records_round_trip_and_cannot_be_changed(store: ProjectStore) -> None:
    store.add_records([record(False), record(True, 0.3)])

    assert store.records() == [record(False), record(True, 0.3)]
    connection = sqlite3.connect(store.path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("UPDATE calibration_records SET wrong = 0")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM calibration_records")
    connection.close()


def test_an_audit_batch_is_checked_then_completed_with_its_records(store: ProjectStore) -> None:
    items = [extraction("sample_size", "120", 0.9), extraction("country", "Ghana", 0.8)]
    batch = store.start_audit(items, seed=3, at=NOW)
    assert store.open_audit() == batch

    store.set_audit_result(
        batch, PAPER.paper_id, "sample_size", checked_value="120", skipped=False, at=NOW
    )
    with pytest.raises(ConfigError, match="1 unchecked items"):
        store.complete_audit(batch, [record(False)], LATER)
    store.set_audit_result(
        batch, PAPER.paper_id, "country", checked_value=None, skipped=True, at=NOW
    )
    store.complete_audit(batch, [record(False)], LATER)

    assert [(i.field, i.status, i.checked_value) for i in store.audit_items(batch)] == [
        ("sample_size", "checked", "120"),
        ("country", "skipped", None),
    ]
    assert store.records() == [record(False)]
    assert store.open_audit() is None
    assert store.audited() == {(PAPER.paper_id, "sample_size"), (PAPER.paper_id, "country")}


def test_a_closed_batch_cannot_change(store: ProjectStore) -> None:
    batch = store.start_audit([extraction("sample_size", "120", 0.9)], seed=1, at=NOW)
    store.set_audit_result(
        batch, PAPER.paper_id, "sample_size", checked_value="120", skipped=False, at=NOW
    )
    store.complete_audit(batch, [], NOW)

    with pytest.raises(ConfigError, match="not open"):
        store.complete_audit(batch, [record(False)], LATER)
    with pytest.raises(ConfigError, match="no open audit batch"):
        store.set_audit_result(
            batch, PAPER.paper_id, "sample_size", checked_value="9", skipped=False, at=LATER
        )
    assert store.records() == []


def test_corrections_never_become_records(store: ProjectStore) -> None:
    store.add_correction(PAPER.paper_id, "country", "Ghana", NOW)
    store.add_correction(PAPER.paper_id, "country", None, LATER)

    assert store.corrections() == {(PAPER.paper_id, "country"): None}
    assert store.records() == []


def result(certified: bool) -> ThresholdResult:
    return ThresholdResult(
        group="sample_size",
        method="fixed_sequence",
        pooled=False,
        alpha=0.1,
        delta=0.1,
        n_cal=40,
        errors_cal=2,
        certified=certified,
        lambda_hat=0.8 if certified else None,
        n_accepted_cal=30 if certified else 0,
        errors_accepted_cal=0,
        upper_bound=0.074 if certified else None,
    )


def test_the_threshold_log_is_versioned_and_append_only(store: ProjectStore) -> None:
    first = store.log_thresholds({"sample_size": result(False)}, n_records=10, at=NOW)
    second = store.log_thresholds({"sample_size": result(True)}, n_records=40, at=LATER)

    log = store.threshold_log()

    assert [(v.version, v.n_records, v.created_at) for v in log] == [
        (first, 10, NOW),
        (second, 40, LATER),
    ]
    assert log[1].results == {"sample_size": result(True)}
    connection = sqlite3.connect(store.path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM threshold_log")
    connection.close()


def test_a_newer_migration_is_applied_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "001_init.sql").write_text(
        (MIGRATIONS / "001_init.sql").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr("exga.store.MIGRATIONS", folder)
    path = tmp_path / "p.sqlite"
    ProjectStore(path)
    (folder / "002_note.sql").write_text(
        "ALTER TABLE papers ADD COLUMN note TEXT;", encoding="utf-8"
    )

    store = ProjectStore(path)
    ProjectStore(path)

    assert store.schema_version() == 2
    with closing(sqlite3.connect(path)) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(papers)")]
    assert columns.count("note") == 1


def test_the_paper_id_is_the_document_hash() -> None:
    assert PAPER.paper_id == hashlib.sha256(b"A total of 120 participants in Ghana.").hexdigest()
