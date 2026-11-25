"""the tables of the thesis (spec 15, ADR 0013), built from result files read as text.

each function takes rows as `exga.tables.read_rows` returns them and gives a ThesisTable:
display rows plus the LaTeX caption and headers. numbers are formatted here, once, so the
LaTeX and CSV versions agree. nothing is computed that the result files do not hold, except
the calibration sizes, which come from `exga.calibrate.required_n`, and the item counts of
a dataset, from the items the experiments load.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from exga.calibrate import required_n
from exga.schemas import FieldSpec
from exga.study import TRUST_STATEMENTS
from exga.tables import Row, latex_table

NOT_AVAILABLE = "n/a"
PERCENT = 100
ALL_FIELDS = "all"
POPULATIONS = {
    "power_beta_4_1_g1": "monotone, linear",
    "power_beta_8_1_g3": "monotone, cubic",
    "discrete_ties": "monotone, five levels",
    "non_monotone_mid_band": "not monotone, middle band",
    "non_monotone_top_band": "not monotone, top band",
}
"""short names of the simulation's populations (exga.simulation.reference_populations)."""
POPULATION_NOTE = (
    r"Populations (score $s$): monotone, linear: $s \sim \mathrm{Beta}(4, 1)$, "
    r"$P(\mathrm{wrong} \mid s) = 1 - s$; monotone, cubic: $s \sim \mathrm{Beta}(8, 1)$, "
    r"$P(\mathrm{wrong} \mid s) = 1 - s^3$; monotone, five levels: $s$ is 0.2, 0.4, 0.6, 0.8 "
    r"or 1 with probability 0.05, 0.05, 0.1, 0.2 and 0.6, and wrong with probability 0.7, "
    r"0.5, 0.3, 0.12 and 0.04; not monotone, middle band: $s \sim \mathrm{Beta}(4, 1)$, wrong "
    r"with probability 0.25 for $0.8 < s \le 0.9$ and 0.02 otherwise; not monotone, top band: "
    r"$s \sim \mathrm{Beta}(5, 1)$, wrong with probability 0.3 for $s > 0.995$ and 0.02 "
    r"otherwise."
)
"""each population's definition, as set in exga.simulation, for the simulation tables."""
BASELINE_NAMES = {
    "accept_all": "accept all",
    "fixed_cutoff": "fixed cut-off at {cutoff}",
    "verify_all": "verify all",
}
STUDY_MEASURES = {
    "manual_minutes": ("Minutes, by hand", "number"),
    "tool_minutes": ("Minutes, with exga", "number"),
    "minutes_difference": ("Minutes, difference", "signed"),
    "manual_accuracy": ("Accuracy, by hand (%)", "rate"),
    "tool_accuracy": ("Accuracy, with exga (%)", "rate"),
    "accuracy_difference": ("Accuracy, difference (pp)", "points"),
    "tool_corrected_share": ("Values corrected with exga (%)", "rate"),
    "sus": ("SUS score (0-100)", "number"),
}
"""participants.csv measures: label, which names the unit, and how values are shown."""
ORDER_MEASURES = ("minutes_difference", "accuracy_difference")
"""the measures reported again by which task came first, to show order effects."""
SOURCE = r"Source: \texttt{{{path}}}."
LINE_BREAK = r"\\"
PERCENT_UNIT = r"(\%)"
"""set in the header of a column of rates, whose cells are percentages without the sign."""


@dataclass(frozen=True)
class ThesisTable:
    """one table: its file name, LaTeX caption, (key, LaTeX header) columns and rows.

    align is the LaTeX column spec; by default the first column is text and the rest numbers.
    """

    name: str
    caption: str
    columns: tuple[tuple[str, str], ...]
    rows: list[Row] = field(default_factory=list)
    note: str | None = None
    align: str | None = None

    def latex(self) -> str:
        """the table as a booktabs LaTeX float labelled tab:<name>."""
        return latex_table(
            self.rows,
            self.columns,
            caption=self.caption,
            label=f"tab:{self.name}",
            align=self.align,
            note=self.note,
        )


def percent(value: object) -> str:
    """a rate as a percentage with one decimal and no sign: the header names the unit.

    None is n/a.
    """
    return NOT_AVAILABLE if value is None else f"{_tenths(float(str(value)) * PERCENT):.1f}"


def interval(low: object, high: object) -> str:
    """a confidence interval of rates, in percent; n/a unless both ends exist."""
    if low is None or high is None:
        return NOT_AVAILABLE
    return f"[{percent(low)}, {percent(high)}]"


def points(value: object) -> str:
    """a difference of two rates in percentage points, with its sign."""
    return NOT_AVAILABLE if value is None else f"{_tenths(float(str(value)) * PERCENT):+.1f}"


def guarantee_table(rows: Sequence[Row]) -> ThesisTable:
    """results/guarantee_simulation.csv: does a certified threshold keep its promise?"""
    return ThesisTable(
        name="guarantee_simulation",
        caption=(
            r"Guarantee simulation: for each population, error level $\alpha$ and number of "
            r"calibration items, the share of 1,000 calibration sets that certified a threshold, "
            r"and the share whose certified threshold had a true error above $\alpha$ "
            r"($\delta = 0.1$; the spec allows up to $\delta + 0.02$)."
        ),
        columns=(
            ("population", "Population"),
            ("alpha", r"$\alpha$"),
            ("n_cal", "Items"),
            ("certified", _stack("Certified", PERCENT_UNIT)),
            ("violated", _stack("Error above", rf"$\alpha$ {PERCENT_UNIT}")),
            ("within", _stack("Within", r"$\delta + 0.02$")),
        ),
        rows=_first_only(
            [
                {
                    "population": _population(row["population"]),
                    "alpha": _level(row["alpha"]),
                    "n_cal": _count(row["n_cal"]),
                    "certified": percent(row["certified_rate"]),
                    "violated": percent(row["violation_rate"]),
                    "within": _yes(row["passes"]),
                }
                for row in rows
            ],
            "population",
        ),
        note=f"{POPULATION_NOTE} {_source('results/guarantee_simulation.csv')}",
        align=_align("l", numbers=5),
    )


def audit_table(rows: Sequence[Row]) -> ThesisTable:
    """results/audit_simulation.csv: random audits against biased logging over 10 rounds."""
    return ThesisTable(
        name="audit_simulation",
        caption=(
            r"Audit simulation: 10 rounds of 400 new items, 5\% of them audited and the "
            r"thresholds recomputed after each round ($\alpha = \delta = 0.1$). "
            r"Version violations are the share of certified threshold versions with a true error "
            r"above $\alpha$; ever violated is the share of runs in which any version was."
        ),
        columns=(
            ("population", "Population"),
            ("policy", "Records"),
            ("versions", _stack("Certified", "versions")),
            ("version_violated", _stack("Version", f"violations {PERCENT_UNIT}")),
            ("ever_violated", _stack("Ever", f"violated {PERCENT_UNIT}")),
        ),
        rows=_first_only(
            [
                {
                    "population": _population(row["population"]),
                    "policy": str(row["policy"]),
                    "versions": _count(row["certified_versions"]),
                    "version_violated": percent(row["version_violation_rate"]),
                    "ever_violated": percent(row["ever_violated_rate"]),
                }
                for row in rows
            ],
            "population",
        ),
        note=f"{POPULATION_NOTE} {_source('results/audit_simulation.csv')}",
        align=_align("l", "l", numbers=3),
    )


def calibration_sizes_table(
    alphas: Sequence[float] = (0.05, 0.1, 0.2), delta: float = 0.1
) -> ThesisTable:
    """the fewest accepted calibration items that certify alpha with 0, 1 or 2 errors."""
    return ThesisTable(
        name="calibration_sizes",
        caption=(
            r"Accepted calibration items needed to certify an error level $\alpha$ at "
            rf"$\delta = {delta}$, by the number of wrong values among them."
        ),
        columns=(
            ("alpha", r"$\alpha$"),
            ("zero", "0 errors"),
            ("one", "1 error"),
            ("two", "2 errors"),
        ),
        rows=[
            {
                "alpha": _level(alpha),
                "zero": str(required_n(alpha, delta, 0)),
                "one": str(required_n(alpha, delta, 1)),
                "two": str(required_n(alpha, delta, 2)),
            }
            for alpha in alphas
        ],
    )


def data_table(
    items: Sequence[tuple[str, FieldSpec, str | None]],
    *,
    name: str,
    dataset: str,
    note: str | None = None,
) -> ThesisTable:
    """items per field, and how many the paper does not report; items are (paper, field, gold).

    fields appear in the order of their first item, then a total over all fields.
    """
    counts: dict[str, list[int]] = {}
    groups: dict[str, str] = {}
    for _, spec, gold in items:
        groups.setdefault(spec.name, spec.group)
        count = counts.setdefault(spec.name, [0, 0])
        count[0] += 1
        count[1] += gold is None
    papers = len({paper for paper, _, _ in items})
    rows: list[Row] = [
        {"field": field, "group": groups[field], "items": _count(n), "not_reported": _count(nr)}
        for field, (n, nr) in counts.items()
    ]
    rows.append(
        {
            "field": "all fields",
            "group": "",
            "items": _count(len(items)),
            "not_reported": _count(sum(nr for _, nr in counts.values())),
        }
    )
    return ThesisTable(
        name=name,
        caption=(
            f"The items of {dataset}: one per paper and field, from {_count(papers)} papers, "
            "and how many of them the paper does not report."
        ),
        columns=(
            ("field", "Field"),
            ("group", "Group"),
            ("items", "Items"),
            ("not_reported", _stack("Not", "reported")),
        ),
        rows=rows,
        note=note,
        align=_align("l", "l", numbers=2),
    )


def main_table(by_group: Sequence[Row], variant: str, model: str, *, dataset: str) -> ThesisTable:
    """by_group.csv for one model and score variant: the spec 11.2 table, all fields first.

    one table per model keeps it within a portrait page.
    """
    rows = sorted(
        (row for row in by_group if row["variant"] == variant and row["model"] == model),
        key=lambda row: (
            row["group"] != ALL_FIELDS,
            str(row["group"]),
            float(str(row["alpha"])),
        ),
    )
    return ThesisTable(
        name=f"results_{model}",
        caption=(
            rf"Results of model {_text(model)} on {dataset} by field group and error level "
            r"$\alpha$. Raw accuracy, accepted, error among accepted (with a 95\% bootstrap "
            r"interval over papers) and certified are on the test papers of the primary split; "
            r"certified share and test error above $\alpha$ are over all splits."
        ),
        columns=(
            ("group", "Fields"),
            ("alpha", r"$\alpha$"),
            ("items", "Items"),
            ("accuracy", _stack("Raw", "accuracy", PERCENT_UNIT)),
            ("accepted", _stack("Accepted", PERCENT_UNIT)),
            ("error", _stack("Error among", f"accepted {PERCENT_UNIT}")),
            ("certified", "Certified"),
            ("certified_share", _stack("Certified", f"share {PERCENT_UNIT}")),
            ("above_alpha", _stack("Test error", r"above $\alpha$", PERCENT_UNIT)),
        ),
        rows=_first_only(
            [
                {
                    "group": "all fields" if row["group"] == ALL_FIELDS else str(row["group"]),
                    "alpha": _level(row["alpha"]),
                    "items": _count(row["test_items"]),
                    "accuracy": percent(row["raw_accuracy"]),
                    "accepted": percent(row["acceptance_rate"]),
                    "error": _with_interval(
                        row["realised_error"], row["error_low"], row["error_high"]
                    ),
                    "certified": _yes(row["certified"]),
                    "certified_share": percent(row["certified_share"]),
                    "above_alpha": percent(row["error_above_alpha_rate"]),
                }
                for row in rows
            ],
            "group",
        ),
        note=(
            r"Test error above $\alpha$ overstates how often the guarantee fails: with a few "
            r"dozen test items per field or fewer, chance alone often puts the observed error "
            r"above $\alpha$ (ADR 0011). The guarantee itself is checked by simulation, where "
            r"the true error is known."
        ),
        align=_align("l", numbers=8),
    )


def baselines_table(baselines: Sequence[Row], variant: str) -> ThesisTable:
    """baselines.csv for one score variant: what the methods without calibration do."""
    return ThesisTable(
        name="baselines",
        caption=(
            r"Baselines on the same test items: share accepted without checking and error "
            r"among accepted, on the primary split and as the mean over all splits."
        ),
        columns=(
            ("model", "Model"),
            ("method", "Method"),
            ("accepted", _stack("Accepted", PERCENT_UNIT)),
            ("error", _stack("Error among", f"accepted {PERCENT_UNIT}")),
            ("mean_accepted", _stack("Mean", f"accepted {PERCENT_UNIT}")),
            ("mean_error", _stack("Mean", f"error {PERCENT_UNIT}")),
        ),
        rows=_first_only(
            [
                {
                    "model": str(row["model"]),
                    "method": BASELINE_NAMES[str(row["baseline"])].format(cutoff=row["cutoff"]),
                    "accepted": percent(row["acceptance_rate"]),
                    "error": percent(row["realised_error"]),
                    "mean_accepted": percent(row["mean_acceptance_rate"]),
                    "mean_error": percent(row["mean_realised_error"]),
                }
                for row in baselines
                if row["variant"] == variant
            ],
            "model",
        ),
        align=_align("l", "l", numbers=4),
    )


def ablation_table(by_group: Sequence[Row]) -> ThesisTable:
    """by_group.csv over all fields, one row per score variant and error level."""
    return ThesisTable(
        name="ablation",
        caption=(
            r"Signal ablation: the same answers scored four ways, each calibrated on its own; "
            r"means over all splits, all fields."
        ),
        columns=(
            ("model", "Model"),
            ("variant", "Score"),
            ("alpha", r"$\alpha$"),
            ("mean_accepted", _stack("Mean", f"accepted {PERCENT_UNIT}")),
            ("mean_error", _stack("Mean error", f"among accepted {PERCENT_UNIT}")),
            ("certified_share", _stack("Certified", f"share {PERCENT_UNIT}")),
        ),
        rows=_first_only(
            [
                {
                    "model": str(row["model"]),
                    "variant": str(row["variant"]),
                    "alpha": _level(row["alpha"]),
                    "mean_accepted": percent(row["mean_acceptance_rate"]),
                    "mean_error": percent(row["mean_realised_error"]),
                    "certified_share": percent(row["certified_share"]),
                }
                for row in by_group
                if row["group"] == ALL_FIELDS
            ],
            "model",
            "variant",
        ),
        align=_align("l", "l", numbers=4),
    )


def fields_table(by_field: Sequence[Row], variant: str, model: str) -> ThesisTable:
    """by_field.csv for one model and variant: which fields certify, at which level.

    rows are grouped by field, in the order the fields first appear, then by level.
    """
    wanted = [row for row in by_field if row["variant"] == variant and row["model"] == model]
    order = list(dict.fromkeys(str(row["field"]) for row in wanted))
    wanted.sort(key=lambda row: (order.index(str(row["field"])), float(str(row["alpha"]))))
    return ThesisTable(
        name=f"fields_{model}",
        caption=(
            rf"Fields of model {_text(model)}: share of splits in which each field certified, "
            r"mean share accepted and raw accuracy, by error level $\alpha$."
        ),
        columns=(
            ("field", "Field"),
            ("group", "Group"),
            ("alpha", r"$\alpha$"),
            ("certified", _stack("Certified", f"share {PERCENT_UNIT}")),
            ("mean_accepted", _stack("Mean", f"accepted {PERCENT_UNIT}")),
            ("accuracy", _stack("Raw", f"accuracy {PERCENT_UNIT}")),
        ),
        rows=_first_only(
            [
                {
                    "field": str(row["field"]),
                    "group": str(row["group"]),
                    "alpha": _level(row["alpha"]),
                    "certified": percent(row["certified_share"]),
                    "mean_accepted": percent(row["mean_acceptance_rate"]),
                    "accuracy": percent(row["raw_accuracy"]),
                }
                for row in wanted
            ],
            "field",
            "group",
        ),
        align=_align("l", "l", numbers=4),
    )


def study_table(summary: Sequence[Row]) -> ThesisTable:
    """results/study/summary.csv: every measure for all participants, and the differences by
    which task came first."""
    wanted = [
        row
        for row in summary
        if row["group"] == "all" or (row["measure"] in ORDER_MEASURES and row["group"] != "all")
    ]
    return ThesisTable(
        name="user_study",
        caption=(
            r"User study: time, accuracy and usability for each task, and the within-person "
            r"differences (exga minus by hand), also by which task came first. "
            r"Quartiles and range are given as [low, high]; pp: percentage points."
        ),
        columns=(
            ("participants", "Participants"),
            ("measure", "Measure"),
            ("n", r"$n$"),
            ("median", "Median"),
            ("iqr", "Quartiles"),
            ("mean", "Mean"),
            ("sd", "SD"),
            ("range", "Range"),
        ),
        rows=_first_only(
            [_study_row(row) for row in wanted if row["measure"] in STUDY_MEASURES],
            "participants",
        ),
        align=_align("l", _wrap(r"0.28\linewidth"), numbers=6),
    )


def trust_table(trust: Sequence[Row]) -> ThesisTable:
    """results/study/trust.csv: answers to each trust statement, never summed (ADR 0012)."""
    return ThesisTable(
        name="trust",
        caption=(
            r"Trust statements after the task with exga: number of participants giving each "
            r"answer, from 1 (strongly disagree) to 5 (strongly agree)."
        ),
        columns=(
            ("statement", "Statement"),
            ("n", r"$n$"),
            *((f"answer_{point}", str(point)) for point in range(1, 6)),
            ("median", "Median"),
        ),
        rows=[
            {
                "statement": statement,
                "n": str(row["n"]),
                **{f"answer_{point}": str(row[f"answer_{point}"]) for point in range(1, 6)},
                "median": _number(row["median"]),
            }
            for statement, row in zip(TRUST_STATEMENTS, trust, strict=True)
        ],
        align=_align(_wrap(r"0.5\linewidth"), numbers=7),
    )


def _study_row(row: Row) -> Row:
    label, unit = STUDY_MEASURES[str(row["measure"])]
    show = {"rate": percent, "points": points, "number": _number, "signed": _signed}[unit]
    # a standard deviation has no sign
    spread = percent if unit in ("rate", "points") else _number
    return {
        "participants": str(row["group"]),
        "measure": label,
        "n": str(row["n"]),
        "median": show(row["median"]),
        "iqr": _pair(show, row["q1"], row["q3"]),
        "mean": show(row["mean"]),
        "sd": spread(row["sd"]),
        "range": _pair(show, row["minimum"], row["maximum"]),
    }


def _pair(show: Callable[[object], str], low: object, high: object) -> str:
    """quartiles or a range as [low, high]; n/a unless both ends exist."""
    return NOT_AVAILABLE if low is None or high is None else f"[{show(low)}, {show(high)}]"


def _align(*text: str, numbers: int) -> str:
    """a LaTeX column spec: the leading text columns as given, then numbers right-aligned.

    a text column is "l", or `_wrap(width)` for text too long for one line.
    """
    return "".join(text) + "r" * numbers


def _source(path: str) -> str:
    """the note naming a table's results file, in typewriter type."""
    return SOURCE.format(path=path.replace("_", r"\_"))


def _wrap(width: str) -> str:
    """a column of text that wraps at width, ragged right (needs \\usepackage{array})."""
    return rf">{{\raggedright\arraybackslash}}p{{{width}}}"


def _stack(*lines: str, align: str = "r") -> str:
    """a header set on several lines (core LaTeX's shortstack), aligned like its column."""
    return rf"\shortstack[{align}]{{" + LINE_BREAK.join(lines) + "}"


def _first_only(rows: list[Row], *keys: str) -> list[Row]:
    """blank labels that repeat the row above, so each block is named once.

    keys are nested blocks, outermost first: a label is blanked only when it and every
    label before it repeat, so a new outer block names its inner labels again.
    """
    shown: list[Row] = []
    for index, row in enumerate(rows):
        blank: Row = {}
        if index > 0:
            above = rows[index - 1]
            for depth, key in enumerate(keys):
                if any(row[k] != above[k] for k in keys[: depth + 1]):
                    break
                blank[key] = ""
        shown.append(row | blank)
    return shown


def _population(name: object) -> str:
    return POPULATIONS.get(str(name), str(name))


def _count(value: object) -> str:
    return f"{int(str(value)):,}"


def _with_interval(value: object, low: object, high: object) -> str:
    shown = percent(value)
    return shown if low is None or high is None else f"{shown} {interval(low, high)}"


def _level(alpha: object) -> str:
    """an error level with two decimals, as the method page writes it: 0.05."""
    return f"{float(str(alpha)):.2f}"


def _number(value: object) -> str:
    return NOT_AVAILABLE if value is None else f"{_tenths(float(str(value))):.1f}"


def _signed(value: object) -> str:
    """a difference with its sign, e.g. +3.0 minutes."""
    return NOT_AVAILABLE if value is None else f"{_tenths(float(str(value))):+.1f}"


def _tenths(value: float) -> float:
    """value rounded to one decimal, so a tiny negative value shows as 0.0, not -0.0."""
    return round(value, 1) + 0.0  # adding 0.0 turns a negative zero into zero


def _yes(value: object) -> str:
    return "yes" if str(value).lower() == "true" else "no"


def _text(value: str) -> str:
    return value.replace("_", r"\_")
