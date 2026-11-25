"""the user-study analysis (spec 11.3, ADR 0012): assignment, SUS, answers and summaries."""

import pytest

from exga.study import ORDERS, Assignment, assign, sus_score


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
