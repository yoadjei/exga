"""the user-study analysis (spec 11.3, ADR 0012): assignment, SUS, answers and summaries."""

import statistics

import pytest

from exga.schemas import FieldSpec
from exga.settings import MatchingSettings
from exga.study import (
    ORDERS,
    Assignment,
    accuracy,
    assign,
    checked_items,
    describe,
    export_answers,
    sheet_answers,
    sus_score,
)


def test_every_block_of_four_participants_covers_each_order_and_set_once() -> None:
    rows = assign(10, seed=0)

    assert [row.participant for row in rows] == [f"P{number:02d}" for number in range(1, 11)]
    for start in (0, 4):
        assert {(row.first, row.first_set) for row in rows[start : start + 4]} == set(ORDERS)
    assert all({row.first, row.second} == {"manual", "tool"} for row in rows)
    assert all({row.first_set, row.second_set} == {"A", "B"} for row in rows)


def test_the_assignment_is_fixed_by_its_seed() -> None:
    assert assign(8, seed=3) == assign(8, seed=3)
    assert assign(8, seed=3) != assign(8, seed=4)


def test_an_assignment_names_the_set_of_each_condition() -> None:
    row = Assignment("P01", first="tool", first_set="B")

    assert (row.second, row.second_set) == ("manual", "A")
    assert (row.paper_set("tool"), row.paper_set("manual")) == ("B", "A")


def test_a_study_needs_participants() -> None:
    with pytest.raises(ValueError, match="at least one"):
        assign(0, seed=0)


@pytest.mark.parametrize(
    ("responses", "score"),
    [
        ([5, 1] * 5, 100.0),
        ([1, 5] * 5, 0.0),
        ([3] * 10, 50.0),
        ([4, 2, 4, 2, 4, 2, 4, 2, 4, 1], 77.5),
    ],
)
def test_sus_scores_follow_brooke(responses: list[int], score: float) -> None:
    assert sus_score(responses) == score


@pytest.mark.parametrize("responses", [[3] * 9, [3] * 9 + [6], [0] + [3] * 9])
def test_sus_needs_ten_answers_from_one_to_five(responses: list[int]) -> None:
    with pytest.raises(ValueError, match="ten answers from 1 to 5"):
        sus_score(responses)


SPECS = {
    "n": FieldSpec(name="n", description="participants", group="numeric"),
    "country": FieldSpec(name="country", description="country", group="short_text"),
}


def test_a_sheet_answer_is_its_value_and_an_empty_cell_is_no_answer() -> None:
    rows = [
        {"paper": "a.pdf", "field": "n", "value": " 120 "},
        {"paper": "a.pdf", "field": "country", "value": "NR"},
        {"paper": "b.pdf", "field": "n", "value": ""},
    ]

    assert sheet_answers(rows) == {("a.pdf", "n"): "120", ("a.pdf", "country"): None}


def test_a_tool_answer_is_the_checked_value_else_the_model_value() -> None:
    rows = [
        {"paper": "a.pdf", "field": "n", "value": "120", "checked_value": ""},
        {"paper": "a.pdf", "field": "country", "value": "Ghana", "checked_value": "NR"},
        {"paper": "b.pdf", "field": "n", "value": "", "checked_value": ""},
        {"paper": "b.pdf", "field": "country", "value": "NR", "checked_value": "'+44 Ghana"},
    ]

    assert export_answers(rows) == {
        ("a.pdf", "n"): "120",
        ("a.pdf", "country"): None,
        ("b.pdf", "country"): "+44 Ghana",
    }
    assert checked_items(rows) == 2


def test_accuracy_counts_right_wrong_and_unanswered_gold_items() -> None:
    gold = {("a.pdf", "n"): "120", ("a.pdf", "country"): "Ghana", ("b.pdf", "n"): "80"}
    answers = {("a.pdf", "n"): "120.0", ("a.pdf", "country"): "Kenya", ("x.pdf", "n"): "1"}

    result = accuracy(answers, gold, SPECS, MatchingSettings())

    assert (result.items, result.correct, result.unanswered) == (3, 1, 1)
    assert result.rate == pytest.approx(1 / 3)


def test_a_summary_gives_centre_and_spread() -> None:
    summary = describe([10.0, 40.0, 20.0, 30.0])

    assert summary is not None
    assert (summary.n, summary.mean, summary.median) == (4, 25.0, 25.0)
    assert (summary.q1, summary.q3, summary.minimum, summary.maximum) == (17.5, 32.5, 10.0, 40.0)
    assert summary.sd == pytest.approx(statistics.stdev([10.0, 20.0, 30.0, 40.0]))


def test_a_summary_of_one_value_has_no_spread_and_of_none_is_empty() -> None:
    one = describe([5.0])

    assert one is not None
    assert (one.sd, one.q1, one.q3) == (None, 5.0, 5.0)
    assert describe([]) is None
