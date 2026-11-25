"""the user-study analysis (spec 11.3, ADR 0012): assignment, SUS, answers and summaries."""

import statistics
from collections.abc import Callable

import pytest

from exga.errors import ConfigError
from exga.schemas import FieldSpec
from exga.settings import MatchingSettings
from exga.study import (
    ORDERS,
    QUESTIONNAIRE_COLUMNS,
    Accuracy,
    Assignment,
    Condition,
    ParticipantResult,
    Responses,
    Session,
    accuracy,
    assign,
    assignment_rows,
    corrected_items,
    describe,
    export_answers,
    questionnaire_rows,
    read_assignments,
    read_minutes,
    read_questionnaire,
    session_rows,
    sheet_answers,
    summary_rows,
    sus_score,
    trust_rows,
)
from exga.tables import Row


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


def test_a_tool_answer_is_the_corrected_value_else_the_model_value() -> None:
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
    assert corrected_items(rows) == 2


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


def as_csv_rows(rows: list[Row]) -> list[dict[str, str]]:
    """rows as a CSV reader returns them: every cell a string, None an empty cell."""
    return [
        {key: "" if value is None else str(value) for key, value in row.items()} for row in rows
    ]


def test_prepared_forms_read_back_as_the_assignment() -> None:
    assignments = assign(5, seed=1)

    assert read_assignments(as_csv_rows(assignment_rows(assignments))) == assignments
    sessions = session_rows(assignments)
    assert [(row["participant"], row["condition"]) for row in sessions[:2]] == [
        ("P01", assignments[0].first),
        ("P01", assignments[0].second),
    ]
    assert all(row["minutes"] is None for row in sessions)
    assert set(questionnaire_rows(assignments)[0]) == set(QUESTIONNAIRE_COLUMNS)


def test_blank_answers_mean_a_participant_has_not_finished() -> None:
    sessions = [
        {"participant": "P01", "condition": "manual", "paper_set": "A", "minutes": "12.5"},
        {"participant": "P01", "condition": "tool", "paper_set": "B", "minutes": ""},
    ]
    complete = {"participant": "P01", "role": "student", "experience": "none"}
    complete |= {f"sus_{n}": "3" for n in range(1, 11)} | {f"trust_{n}": "4" for n in range(1, 5)}
    partial = complete | {"participant": "P02", "trust_4": ""}

    assert read_minutes(sessions) == {("P01", "manual"): 12.5}
    responses = read_questionnaire([complete, partial])
    assert list(responses) == ["P01"]
    assert (responses["P01"].sus, responses["P01"].trust) == ((3,) * 10, (4,) * 4)


@pytest.mark.parametrize(
    ("reader", "row", "problem"),
    [
        (read_minutes, {"participant": "P03", "condition": "tool", "minutes": "ten"}, "P03"),
        (read_minutes, {"participant": "P03", "condition": "tool", "minutes": "-1"}, "P03"),
        (read_minutes, {"participant": "P03", "condition": "tablet", "minutes": "5"}, "tablet"),
        (read_assignments, {"participant": "P03", "first_condition": "x", "first_set": "A"}, "x"),
    ],
)
def test_bad_form_values_name_the_participant_or_value(
    reader: Callable[[list[dict[str, str]]], object], row: dict[str, str], problem: str
) -> None:
    with pytest.raises(ConfigError, match=problem):
        reader([row])


def test_a_questionnaire_answer_outside_the_scale_is_refused() -> None:
    row = {"participant": "P04", "role": "student", "experience": "some"}
    row |= {f"sus_{n}": "3" for n in range(1, 11)} | {f"trust_{n}": "4" for n in range(1, 5)}

    with pytest.raises(ConfigError, match=r"P04.*sus_2"):
        read_questionnaire([row | {"sus_2": "6"}])
    with pytest.raises(ConfigError, match=r"P04.*role"):
        read_questionnaire([row | {"role": "teacher"}])


def result(participant: str, first: Condition, minutes: tuple[float, float]) -> ParticipantResult:
    return ParticipantResult(
        assignment=Assignment(participant, first=first, first_set="A"),
        manual=Session(minutes[0], Accuracy(items=10, correct=8, unanswered=1)),
        tool=Session(minutes[1], Accuracy(items=10, correct=9, unanswered=0)),
        corrected=4,
        responses=Responses("student", "none", sus=(4, 2) * 5, trust=(4, 5, 3, 4)),
    )


def test_results_are_summarised_overall_and_by_order() -> None:
    results = [result("P01", "manual", (20.0, 10.0)), result("P02", "tool", (30.0, 12.0))]

    row = results[0].row()
    summary = {(r["group"], r["measure"]): r for r in summary_rows(results)}
    trust = trust_rows(results)

    assert (row["minutes_difference"], row["accuracy_difference"]) == (-10.0, pytest.approx(0.1))
    assert (row["tool_corrected_share"], row["sus"], row["manual_set"]) == (0.4, 75.0, "A")
    assert summary["all", "minutes_difference"]["n"] == 2
    assert summary["all", "minutes_difference"]["median"] == -14.0
    assert summary["manual first", "tool_minutes"]["mean"] == 10.0
    assert summary["tool first", "manual_minutes"]["mean"] == 30.0
    assert trust[1] == {
        "item": "trust_2",
        "n": 2,
        "median": 5.0,
        "answer_1": 0,
        "answer_2": 0,
        "answer_3": 0,
        "answer_4": 0,
        "answer_5": 2,
    }


def test_an_empty_group_is_summarised_as_no_data() -> None:
    rows = summary_rows([result("P01", "manual", (20.0, 10.0))])

    empty = next(r for r in rows if r["group"] == "tool first" and r["measure"] == "sus")
    assert (empty["n"], empty["mean"], empty["median"]) == (0, None, None)
