"""the user study (spec 11.3, ADR 0012): who does what, and how the answers are scored.

each participant extracts the same fields from two small paper sets, one by hand and one with
exga. the order of conditions and the set each one uses are counterbalanced. the study is
reported descriptively; nothing here tests a hypothesis.
"""

import random
from dataclasses import dataclass
from typing import Literal

Condition = Literal["manual", "tool"]
PaperSet = Literal["A", "B"]

ORDERS: tuple[tuple[Condition, PaperSet], ...] = (
    ("manual", "A"),
    ("tool", "A"),
    ("manual", "B"),
    ("tool", "B"),
)
"""the four (first condition, its paper set) pairs; the second session is the other of each."""
SUS_ITEMS = 10
SUS_SCALE = range(1, 6)
SUS_MULTIPLIER = 2.5
"""a raw SUS total of 0-40 becomes 0-100 (Brooke, 1996)."""


@dataclass(frozen=True)
class Assignment:
    """one participant's two sessions: a condition and a paper set first, the others second."""

    participant: str
    first: Condition
    first_set: PaperSet

    @property
    def second(self) -> Condition:
        """the condition of the second session."""
        return "tool" if self.first == "manual" else "manual"

    @property
    def second_set(self) -> PaperSet:
        """the paper set of the second session."""
        return "B" if self.first_set == "A" else "A"

    def paper_set(self, condition: Condition) -> PaperSet:
        """the paper set this participant works on in condition."""
        return self.first_set if condition == self.first else self.second_set


def assign(participants: int, seed: int) -> list[Assignment]:
    """counterbalanced assignments for participants P01, P02, ...

    each consecutive block of four gets every order in ORDERS once, in a seeded random
    permutation, so a study that stops early is still close to balanced.

    raises ValueError for fewer than one participant.
    """
    if participants < 1:
        raise ValueError("a study needs at least one participant")
    generator = random.Random(seed)
    orders: list[tuple[Condition, PaperSet]] = []
    while len(orders) < participants:
        orders += generator.sample(ORDERS, len(ORDERS))
    return [
        Assignment(f"P{number:02d}", first, paper_set)
        for number, (first, paper_set) in enumerate(orders[:participants], start=1)
    ]


def sus_score(responses: list[int]) -> float:
    """the System Usability Scale score, 0-100, of ten answers on a 1-5 scale (Brooke, 1996).

    odd items are worded positively and count answer - 1; even items negatively and count
    5 - answer. raises ValueError unless there are ten answers from 1 to 5.
    """
    if len(responses) != SUS_ITEMS or any(answer not in SUS_SCALE for answer in responses):
        raise ValueError(f"SUS needs ten answers from 1 to 5, got {responses}")
    total = sum(
        answer - 1 if number % 2 else max(SUS_SCALE) - answer
        for number, answer in enumerate(responses, start=1)
    )
    return total * SUS_MULTIPLIER
