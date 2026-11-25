import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from exga.document import text_document
from exga.errors import ConfigError
from exga.project import (
    current_thresholds,
    draw_next_audit,
    finish_audit,
    import_records,
    save_scored,
)
from exga.schemas import CalibrationRecord, Extraction, FieldSpec, Signals
from exga.settings import AuditSettings, CalibrationSettings, Settings
from exga.store import ProjectStore

NOW = datetime(2026, 11, 25, tzinfo=UTC)
SPEC = FieldSpec(name="sample_size", description="participants", group="numeric")
SETTINGS = Settings(calibration=CalibrationSettings(alpha=0.1), audit=AuditSettings(rate=0.1))
PAPERS = [
    text_document(f"Paper {i}: a total of {100 + i} participants.", f"p{i}.md") for i in range(40)
]


def extraction(index: int, score: float) -> Extraction:
    return Extraction(
        paper_id=PAPERS[index].paper_id,
        field="sample_size",
        samples=(),
        value=str(100 + index),
        evidence=None,
        signals=Signals(agreement=score),
        score=score,
        model_id="mock",
        prompt_version="extract_v1",
    )


@pytest.fixture
def store(tmp_path: Path) -> ProjectStore:
    store = ProjectStore(tmp_path / "project.sqlite")
    store.save_fields([SPEC])
    for paper in PAPERS:
        store.add_paper(paper, None, NOW)
    save_scored(store, [extraction(i, score=0.5 + i / 100) for i in range(40)], NOW)
    return store


def benchmark_records(n: int, wrong_every: int = 0) -> list[CalibrationRecord]:
    return [
        CalibrationRecord(
            paper_id=hashlib.sha256(f"benchmark {i}".encode()).hexdigest(),
            field="sample_size",
            group="numeric",
            score=0.95,
            wrong=bool(wrong_every) and i % wrong_every == 0,
            source="benchmark",
            created_at=NOW,
        )
        for i in range(n)
    ]


def test_before_calibration_every_item_is_not_certifiable(store: ProjectStore) -> None:
    assert current_thresholds(store) == {}
    assert {e.decision for e in store.extractions()} == {"NOT_CERTIFIABLE"}


def test_imported_records_recalibrate_and_redecide(store: ProjectStore) -> None:
    version = import_records(store, benchmark_records(40), SETTINGS, NOW)

    assert version.version == 1
    assert version.results["sample_size"].certified
    assert current_thresholds(store) == version.results
    decisions = {e.decision for e in store.extractions()}
    assert decisions <= {"ACCEPT", "FLAG"}
    assert "NOT_CERTIFIABLE" not in decisions


def test_audit_records_cannot_be_imported(store: ProjectStore) -> None:
    forged = benchmark_records(1)[0].model_copy(update={"source": "random_audit"})

    with pytest.raises(ConfigError, match="only from completed audit batches"):
        import_records(store, [forged], SETTINGS, NOW)


def test_an_audit_round_trip_adds_records_and_a_threshold_version(store: ProjectStore) -> None:
    batch = draw_next_audit(store, SETTINGS, NOW)
    assert batch is not None
    assert draw_next_audit(store, SETTINGS, NOW) == batch  # the open batch is reused
    items = store.audit_items(batch)
    assert len(items) == 4
    extracted = {e.paper_id: e.value for e in store.extractions()}
    # the person confirms every value except the first, which the paper does not report
    for index, item in enumerate(items):
        value = None if index == 0 else extracted[item.paper_id]
        store.set_audit_result(
            batch, item.paper_id, item.field, checked_value=value, skipped=False, at=NOW
        )

    version = finish_audit(store, batch, SETTINGS, NOW + timedelta(hours=1))

    records = store.records()
    assert [r.source for r in records] == ["random_audit"] * 4
    assert sum(r.wrong for r in records) == 1
    assert version.n_records == 4
    assert store.open_audit() is None


def test_later_audits_never_redraw_an_item(store: ProjectStore) -> None:
    drawn: list[tuple[str, str]] = []
    while (batch := draw_next_audit(store, SETTINGS, NOW)) is not None:
        for item in store.audit_items(batch):
            drawn.append((item.paper_id, item.field))
            store.set_audit_result(
                batch, item.paper_id, item.field, checked_value=None, skipped=True, at=NOW
            )
        finish_audit(store, batch, SETTINGS, NOW)

    assert len(drawn) == len(set(drawn)) == 40
    assert store.records() == []


def test_draws_are_seeded_by_batch_number(tmp_path: Path, store: ProjectStore) -> None:
    other = ProjectStore(tmp_path / "copy.sqlite")
    other.save_fields([SPEC])
    for paper in PAPERS:
        other.add_paper(paper, None, NOW)
    save_scored(other, store.extractions(), NOW)

    first = draw_next_audit(store, SETTINGS, NOW)
    second = draw_next_audit(other, SETTINGS, NOW)

    assert first is not None
    assert second is not None
    assert store.audit_items(first) == other.audit_items(second)
