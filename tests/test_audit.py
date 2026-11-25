import hashlib
from collections import Counter
from datetime import UTC, datetime

import pytest
from scipy import stats

from exga.audit import audit_record, audit_size, draw_audit, recalibrate
from exga.schemas import Extraction, FieldSpec, Signals
from exga.settings import AuditSettings, CalibrationSettings, MatchingSettings

SETTINGS = AuditSettings()
RULES = MatchingSettings()
NOW = datetime(2026, 11, 25, tzinfo=UTC)
SPEC = FieldSpec(name="sample_size", description="participants", group="numeric")


def extraction(index: int, score: float, decision: str = "FLAG") -> Extraction:
    return Extraction(
        paper_id=hashlib.sha256(str(index).encode()).hexdigest(),
        field="sample_size",
        samples=(),
        value="120",
        evidence=None,
        signals=Signals(agreement=score),
        score=score,
        decision=decision,  # type: ignore[arg-type]
        model_id="mock",
        prompt_version="extract_v1",
    )


ITEMS = [extraction(i, score=i / 40, decision="ACCEPT" if i >= 30 else "FLAG") for i in range(40)]


@pytest.mark.parametrize(
    ("n_items", "expected"), [(0, 0), (2, 2), (10, 3), (60, 3), (61, 4), (1000, 50)]
)
def test_the_batch_is_five_percent_rounded_up_but_at_least_three(
    n_items: int, expected: int
) -> None:
    assert audit_size(n_items, SETTINGS) == expected


def test_a_draw_is_reproducible_and_in_item_order() -> None:
    first = draw_audit(ITEMS, SETTINGS, seed=5)

    assert first == draw_audit(ITEMS, SETTINGS, seed=5)
    assert [ITEMS.index(item) for item in first] == sorted(ITEMS.index(item) for item in first)
    assert first != draw_audit(ITEMS, SETTINGS, seed=6)


def test_every_item_is_equally_likely_whatever_its_score_or_decision() -> None:
    counts = Counter(
        ITEMS.index(item) for seed in range(4000) for item in draw_audit(ITEMS, SETTINGS, seed)
    )

    observed = [counts[index] for index in range(len(ITEMS))]
    # 4000 draws of 3 from 40: 300 expected per item; a chi-square test at the 0.1% level
    assert stats.chisquare(observed).pvalue > 0.001
    accepted = sum(counts[index] for index in range(30, 40))
    assert accepted / sum(observed) == pytest.approx(10 / 40, abs=0.02)


@pytest.mark.parametrize(
    ("checked", "wrong"), [("120", False), ("120.0", False), ("121", True), (None, True)]
)
def test_an_audit_record_applies_the_correctness_rule(checked: str | None, wrong: bool) -> None:
    record = audit_record(ITEMS[3], checked, SPEC, RULES, NOW)

    assert (record.wrong, record.source, record.score) == (wrong, "random_audit", 3 / 40)
    assert (record.paper_id, record.field, record.group) == (
        ITEMS[3].paper_id,
        "sample_size",
        "numeric",
    )


def test_recalibration_gives_every_field_a_result() -> None:
    records = [audit_record(item, "120", SPEC, RULES, NOW) for item in ITEMS]

    [(field, result)] = recalibrate(records, [SPEC], CalibrationSettings(alpha=0.1)).items()

    assert field == "sample_size"
    assert (result.n_cal, result.errors_cal, result.certified) == (40, 0, True)
