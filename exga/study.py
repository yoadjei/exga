"""the user study (spec 11.3, ADR 0012): who does what, and how the answers are scored.

each participant extracts the same fields from two small paper sets, one by hand and one with
exga. the order of conditions and the set each one uses are counterbalanced. the study is
reported descriptively; nothing here tests a hypothesis.
"""

import math
import random
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Literal

from exga.errors import ConfigError
from exga.export import read_cell
from exga.labels import NOT_REPORTED
from exga.matching import is_correct
from exga.schemas import FieldSpec
from exga.settings import MatchingSettings
from exga.tables import Row

Condition = Literal["manual", "tool"]
PaperSet = Literal["A", "B"]
Answers = dict[tuple[str, str], str | None]
"""(paper file name, field) -> value; None means "not reported"."""

ORDERS: tuple[tuple[Condition, PaperSet], ...] = (
    ("manual", "A"),
    ("tool", "A"),
    ("manual", "B"),
    ("tool", "B"),
)
"""the four (first condition, its paper set) pairs; the second session is the other of each."""
PAPER_SETS: tuple[PaperSet, ...] = ("A", "B")
SUS_ITEMS = 10
SUS_SCALE = range(1, 6)
SUS_MULTIPLIER = 2.5
"""a raw SUS total of 0-40 becomes 0-100 (Brooke, 1996)."""
TRUST_STATEMENTS = (
    "I trusted the values marked Accepted without checking them myself.",
    "The highlighted evidence helped me decide whether a value was right.",
    "I understood why some values were marked Check.",
    "I would rely on values marked Accepted in a real review.",
)
"""the trust statements of study/questionnaire.md, in order; written for this study."""
TRUST_ITEMS = len(TRUST_STATEMENTS)
CONDITIONS: tuple[Condition, ...] = ("manual", "tool")
ROLES = ("student", "researcher", "other")
EXPERIENCE = ("none", "some", "much")
"""prior experience of extracting data from papers, as the questionnaire asks it."""
SUS_COLUMNS = tuple(f"sus_{number}" for number in range(1, SUS_ITEMS + 1))
TRUST_COLUMNS = tuple(f"trust_{number}" for number in range(1, TRUST_ITEMS + 1))
QUESTIONNAIRE_COLUMNS = ("participant", "role", "experience", *SUS_COLUMNS, *TRUST_COLUMNS)
MEASURES = (
    "manual_minutes",
    "tool_minutes",
    "minutes_difference",
    "manual_accuracy",
    "tool_accuracy",
    "accuracy_difference",
    "tool_corrected_share",
    "sus",
)
"""the participants.csv columns that summary.csv describes."""
_SPREAD = ("mean", "sd", "median", "q1", "q3", "minimum", "maximum")


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


def sheet_answers(rows: Iterable[Mapping[str, str | None]]) -> Answers:
    """a filled manual sheet (columns paper, field, value) as answers.

    "NR" means the participant found the field not reported (None); an empty cell is no
    answer and is left out, so it counts as unanswered.
    """
    answers: Answers = {}
    for row in rows:
        value = (row["value"] or "").strip()
        if value:
            answers[_key(row)] = None if value == NOT_REPORTED else value
    return answers


def export_answers(rows: Iterable[Mapping[str, str | None]]) -> Answers:
    """an exga results.csv as answers: the value the participant saved, else the model's.

    an empty final value (a failed extraction nobody corrected) is no answer and is left out.
    """
    answers: Answers = {}
    for row in rows:
        checked = read_cell(row["checked_value"] or "")
        value = checked or read_cell(row["value"] or "")
        if value:
            answers[_key(row)] = None if value == NOT_REPORTED else value
    return answers


def corrected_items(rows: Iterable[Mapping[str, str | None]]) -> int:
    """how many items of an exga results.csv a person saved a value for.

    the Review page records corrections only, so a value checked and found right leaves no
    trace; this counts corrections (including any that repeat the model's value).
    """
    return sum(bool(row["checked_value"]) for row in rows)


@dataclass(frozen=True)
class Accuracy:
    """how many of a paper set's gold items a participant answered correctly."""

    items: int
    correct: int
    unanswered: int

    @property
    def rate(self) -> float:
        """share of items answered correctly; unanswered items count as wrong."""
        return self.correct / self.items


def accuracy(
    answers: Mapping[tuple[str, str], str | None],
    gold: Mapping[tuple[str, str], str | None],
    specs: Mapping[str, FieldSpec],
    rules: MatchingSettings,
) -> Accuracy:
    """score answers against gold with each field's correctness rule (spec 6.4).

    every gold item counts; answers to items without gold are ignored.
    """
    correct = sum(
        key in answers and is_correct(answers[key], truth, specs[key[1]], rules)
        for key, truth in gold.items()
    )
    unanswered = sum(key not in answers for key in gold)
    return Accuracy(items=len(gold), correct=correct, unanswered=unanswered)


@dataclass(frozen=True)
class Summary:
    """centre and spread of one measure; sd is undefined for a single value."""

    n: int
    mean: float
    sd: float | None
    median: float
    q1: float
    q3: float
    minimum: float
    maximum: float


def describe(values: Sequence[float]) -> Summary | None:
    """a descriptive summary of values (quartiles inclusive of the extremes); None if empty."""
    if not values:
        return None
    if len(values) == 1:
        q1 = q3 = values[0]
    else:
        q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return Summary(
        n=len(values),
        mean=statistics.fmean(values),
        sd=statistics.stdev(values) if len(values) > 1 else None,
        median=statistics.median(values),
        q1=q1,
        q3=q3,
        minimum=min(values),
        maximum=max(values),
    )


def _key(row: Mapping[str, str | None]) -> tuple[str, str]:
    return read_cell(row["paper"] or "").strip(), (row["field"] or "").strip()


@dataclass(frozen=True)
class Responses:
    """one participant's questionnaire, answered after the tool condition."""

    role: str
    experience: str
    sus: tuple[int, ...]
    trust: tuple[int, ...]


def assignment_rows(assignments: Sequence[Assignment]) -> list[Row]:
    """assignment.csv: who does which condition on which set, in which order."""
    return [
        {
            "participant": row.participant,
            "first_condition": row.first,
            "first_set": row.first_set,
            "second_condition": row.second,
            "second_set": row.second_set,
        }
        for row in assignments
    ]


def session_rows(assignments: Sequence[Assignment]) -> list[Row]:
    """sessions.csv in session order, with minutes left blank for the researcher."""
    return [
        {
            "participant": row.participant,
            "condition": condition,
            "paper_set": row.paper_set(condition),
            "minutes": None,
        }
        for row in assignments
        for condition in (row.first, row.second)
    ]


def questionnaire_rows(assignments: Sequence[Assignment]) -> list[Row]:
    """questionnaire.csv with every answer left blank."""
    return [
        {"participant": row.participant, **dict.fromkeys(QUESTIONNAIRE_COLUMNS[1:])}
        for row in assignments
    ]


def read_assignments(rows: Iterable[Mapping[str, str | None]]) -> list[Assignment]:
    """assignment.csv as written by `assignment_rows`; raises ConfigError for a bad value."""
    by_text: dict[tuple[str, str], tuple[Condition, PaperSet]] = {order: order for order in ORDERS}
    assignments = []
    for row in rows:
        participant = _cell(row, "participant")
        text = (_cell(row, "first_condition"), _cell(row, "first_set"))
        if text not in by_text:
            raise ConfigError(
                f"assignment of {participant}: {text[0]!r} on set {text[1]!r} is not a "
                "condition (manual, tool) on a paper set (A, B)"
            )
        first, paper_set = by_text[text]
        assignments.append(Assignment(participant, first, paper_set))
    return assignments


def read_minutes(rows: Iterable[Mapping[str, str | None]]) -> dict[tuple[str, Condition], float]:
    """sessions.csv as {(participant, condition): minutes}; a blank time is left out.

    raises ConfigError for an unknown condition or a time that is not a positive number.
    """
    by_text: dict[str, Condition] = {condition: condition for condition in CONDITIONS}
    minutes: dict[tuple[str, Condition], float] = {}
    for row in rows:
        participant, text = _cell(row, "participant"), _cell(row, "minutes")
        condition = by_text.get(_cell(row, "condition"))
        if condition is None:
            raise ConfigError(
                f"sessions of {participant}: unknown condition {_cell(row, 'condition')!r}"
            )
        if not text:
            continue
        try:
            value = float(text)
        except ValueError:
            value = math.nan
        if not value > 0:
            raise ConfigError(
                f"sessions of {participant}: minutes {text!r} is not a positive number"
            )
        minutes[participant, condition] = value
    return minutes


def read_questionnaire(rows: Iterable[Mapping[str, str | None]]) -> dict[str, Responses]:
    """questionnaire.csv as {participant: responses}; a row with a blank answer is left out.

    raises ConfigError, naming the participant and column, for a value outside its scale.
    """
    points = {str(point) for point in SUS_SCALE}
    responses = {}
    for row in rows:
        participant = _cell(row, "participant")
        cells = {column: _cell(row, column) for column in QUESTIONNAIRE_COLUMNS[1:]}
        if not all(cells.values()):
            continue
        for column, allowed in (("role", ROLES), ("experience", EXPERIENCE)):
            if cells[column] not in allowed:
                raise ConfigError(
                    f"questionnaire of {participant}: {column} {cells[column]!r} is not one of "
                    f"{', '.join(allowed)}"
                )
        for column in (*SUS_COLUMNS, *TRUST_COLUMNS):
            if cells[column] not in points:
                raise ConfigError(
                    f"questionnaire of {participant}: {column} {cells[column]!r} is not a "
                    "whole number from 1 to 5"
                )
        responses[participant] = Responses(
            role=cells["role"],
            experience=cells["experience"],
            sus=tuple(int(cells[column]) for column in SUS_COLUMNS),
            trust=tuple(int(cells[column]) for column in TRUST_COLUMNS),
        )
    return responses


@dataclass(frozen=True)
class Session:
    """one condition of one participant: how long it took and how accurate the answers were."""

    minutes: float
    accuracy: Accuracy


@dataclass(frozen=True)
class ParticipantResult:
    """everything measured for one participant who completed the study."""

    assignment: Assignment
    manual: Session
    tool: Session
    corrected: int
    """items of the tool condition the participant saved a corrected value for."""
    responses: Responses

    def row(self) -> Row:
        """one row of participants.csv; differences are tool minus manual."""
        return {
            "participant": self.assignment.participant,
            "first_condition": self.assignment.first,
            "manual_set": self.assignment.paper_set("manual"),
            "tool_set": self.assignment.paper_set("tool"),
            "manual_minutes": self.manual.minutes,
            "tool_minutes": self.tool.minutes,
            "minutes_difference": self.tool.minutes - self.manual.minutes,
            "manual_accuracy": self.manual.accuracy.rate,
            "tool_accuracy": self.tool.accuracy.rate,
            "accuracy_difference": self.tool.accuracy.rate - self.manual.accuracy.rate,
            "manual_unanswered": self.manual.accuracy.unanswered,
            "tool_unanswered": self.tool.accuracy.unanswered,
            "tool_items": self.tool.accuracy.items,
            "tool_corrected": self.corrected,
            "tool_corrected_share": self.corrected / self.tool.accuracy.items,
            "sus": sus_score(list(self.responses.sus)),
            "role": self.responses.role,
            "experience": self.responses.experience,
        }


def summary_rows(results: Sequence[ParticipantResult]) -> list[Row]:
    """summary.csv: each measure described for everyone, then by which condition came first."""
    groups = {
        "all": results,
        "manual first": [result for result in results if result.assignment.first == "manual"],
        "tool first": [result for result in results if result.assignment.first == "tool"],
    }
    rows: list[Row] = []
    for group, members in groups.items():
        participant_rows = [member.row() for member in members]
        for measure in MEASURES:
            summary = describe([float(str(row[measure])) for row in participant_rows])
            cells = asdict(summary) if summary else {"n": 0, **dict.fromkeys(_SPREAD)}
            rows.append({"group": group, "measure": measure, **cells})
    return rows


def trust_rows(results: Sequence[ParticipantResult]) -> list[Row]:
    """trust.csv: how often each answer was given to each trust item, with the median.

    the items are not a validated scale, so they are reported one by one, never summed.
    """
    rows: list[Row] = []
    for index, column in enumerate(TRUST_COLUMNS):
        answers = [result.responses.trust[index] for result in results]
        rows.append(
            {
                "item": column,
                "n": len(answers),
                "median": statistics.median(answers) if answers else None,
                **{f"answer_{point}": answers.count(point) for point in SUS_SCALE},
            }
        )
    return rows


def _cell(row: Mapping[str, str | None], column: str) -> str:
    return (row.get(column) or "").strip()
