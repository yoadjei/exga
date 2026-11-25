"""the tables of the thesis (spec 15, ADR 0013), built from result files read as text.

each function takes rows as `exga.tables.read_rows` returns them and gives a ThesisTable:
display rows plus the LaTeX caption and headers. numbers are formatted here, once, so the
LaTeX and CSV versions agree. nothing is computed that the result files do not hold, except
the calibration sizes, which come from `exga.calibrate.required_n`.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from exga.calibrate import required_n
from exga.study import TRUST_STATEMENTS
from exga.tables import Row, latex_table

NOT_AVAILABLE = "n/a"
PERCENT = 100
ALL_FIELDS = "all"
POPULATIONS = {
    "power_beta_4_1_g1": "monotone: Beta(4, 1) scores, P(wrong) = 1 - s",
    "power_beta_8_1_g3": "monotone: Beta(8, 1) scores, P(wrong) = 1 - s cubed",
    "discrete_ties": "monotone with ties: five score levels",
    "non_monotone_mid_band": "not monotone: error band at 0.8-0.9",
    "non_monotone_top_band": "not monotone: errors above 0.995",
}
"""the guarantee simulation's populations (exga.simulation), described for a reader."""
BASELINE_NAMES = {
    "accept_all": "accept all",
    "fixed_cutoff": "fixed cut-off at {cutoff}",
    "verify_all": "verify all",
}
STUDY_MEASURES = {
    "manual_minutes": ("Minutes, by hand", "minutes"),
    "tool_minutes": ("Minutes, with exga", "minutes"),
    "minutes_difference": ("Minutes, exga minus by hand", "minutes"),
    "manual_accuracy": ("Accuracy, by hand", "rate"),
    "tool_accuracy": ("Accuracy, with exga", "rate"),
    "accuracy_difference": ("Accuracy, exga minus by hand", "points"),
    "tool_corrected_share": ("Share of values corrected with exga", "rate"),
    "sus": ("SUS score (0-100)", "minutes"),
}
"""participants.csv measures: label and unit; "minutes" also serves any plain number."""
ORDER_MEASURES = ("minutes_difference", "accuracy_difference")
"""the measures reported again by which task came first, to show order effects."""
SOURCE = r"Source: \texttt{{{path}}}."


@dataclass(frozen=True)
class ThesisTable:
    """one table: its file name, LaTeX caption, (key, LaTeX header) columns and rows."""

    name: str
    caption: str
    columns: tuple[tuple[str, str], ...]
    rows: list[Row] = field(default_factory=list)
    note: str | None = None

    def latex(self) -> str:
        """the table as a booktabs LaTeX float labelled tab:<name>."""
        return latex_table(
            self.rows, self.columns, caption=self.caption, label=f"tab:{self.name}", note=self.note
        )


def percent(value: object) -> str:
    """a rate as a percentage with one decimal; None is n/a."""
    return NOT_AVAILABLE if value is None else f"{float(str(value)) * PERCENT:.1f}%"


def interval(low: object, high: object) -> str:
    """a confidence interval of rates; n/a unless both ends exist."""
    if low is None or high is None:
        return NOT_AVAILABLE
    return f"[{percent(low)}, {percent(high)}]"


def points(value: object) -> str:
    """a difference of two rates in percentage points, with its sign."""
    return NOT_AVAILABLE if value is None else f"{float(str(value)) * PERCENT:+.1f} pp"


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
            ("certified", "Certified"),
            ("violated", "Error above $\\alpha$"),
            ("within", r"Within $\delta + 0.02$"),
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
        note=SOURCE.format(path="results/guarantee\\_simulation.csv"),
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
            ("versions", "Certified versions"),
            ("version_violated", "Version violations"),
            ("ever_violated", "Ever violated"),
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
        note=SOURCE.format(path="results/audit\\_simulation.csv"),
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


def main_table(by_group: Sequence[Row], variant: str, *, name: str, dataset: str) -> ThesisTable:
    """by_group.csv for one score variant: the spec 11.2 table, all fields first."""
    rows = sorted(
        (row for row in by_group if row["variant"] == variant),
        key=lambda row: (str(row["model"]), row["group"] != ALL_FIELDS, str(row["group"])),
    )
    return ThesisTable(
        name=name,
        caption=(
            rf"Results on {dataset} by model, field group and error level $\alpha$. Accepted "
            r"and error among accepted are on the test papers of the primary split, with 95\% "
            r"bootstrap intervals over papers; certified share and test error above $\alpha$ "
            r"are over all splits."
        ),
        columns=(
            ("model", "Model"),
            ("group", "Fields"),
            ("alpha", r"$\alpha$"),
            ("items", "Items"),
            ("accuracy", "Raw accuracy"),
            ("accepted", "Accepted"),
            ("error", "Error among accepted"),
            ("certified", "Certified"),
            ("certified_share", "Certified share"),
            ("above_alpha", r"Test error above $\alpha$"),
        ),
        rows=[
            {
                "model": str(row["model"]),
                "group": "all fields" if row["group"] == ALL_FIELDS else str(row["group"]),
                "alpha": _level(row["alpha"]),
                "items": str(row["test_items"]),
                "accuracy": percent(row["raw_accuracy"]),
                "accepted": _with_interval(
                    row["acceptance_rate"], row["acceptance_low"], row["acceptance_high"]
                ),
                "error": _with_interval(row["realised_error"], row["error_low"], row["error_high"]),
                "certified": _yes(row["certified"]),
                "certified_share": percent(row["certified_share"]),
                "above_alpha": percent(row["error_above_alpha_rate"]),
            }
            for row in rows
        ],
        note=(
            r"Test error above $\alpha$ overstates how often the guarantee fails: with about "
            r"26 test items per field, chance alone often puts the observed error above "
            r"$\alpha$ (ADR 0011)."
        ),
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
            ("accepted", "Accepted"),
            ("error", "Error among accepted"),
            ("mean_accepted", "Mean accepted"),
            ("mean_error", "Mean error"),
        ),
        rows=[
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
            ("mean_accepted", "Mean accepted"),
            ("mean_error", "Mean error among accepted"),
            ("certified_share", "Certified share"),
        ),
        rows=[
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
    )


def fields_table(by_field: Sequence[Row], variant: str, model: str) -> ThesisTable:
    """by_field.csv for one model and variant: which fields certify, at which level."""
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
            ("certified", "Certified share"),
            ("mean_accepted", "Mean accepted"),
            ("accuracy", "Raw accuracy"),
        ),
        rows=[
            {
                "field": str(row["field"]),
                "group": str(row["group"]),
                "alpha": _level(row["alpha"]),
                "certified": percent(row["certified_share"]),
                "mean_accepted": percent(row["mean_acceptance_rate"]),
                "accuracy": percent(row["raw_accuracy"]),
            }
            for row in by_field
            if row["variant"] == variant and row["model"] == model
        ],
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
            r"differences (exga minus by hand), also by which task came first."
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
        rows=[_study_row(row) for row in wanted if row["measure"] in STUDY_MEASURES],
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
    )


def _study_row(row: Row) -> Row:
    label, unit = STUDY_MEASURES[str(row["measure"])]
    show = {"rate": percent, "points": points, "minutes": _number}[unit]
    return {
        "participants": str(row["group"]),
        "measure": label,
        "n": str(row["n"]),
        "median": show(row["median"]),
        "iqr": NOT_AVAILABLE if row["q1"] is None else f"[{show(row['q1'])}, {show(row['q3'])}]",
        "mean": show(row["mean"]),
        "sd": NOT_AVAILABLE if row["sd"] is None else _spread(row["sd"], unit),
        "range": (
            NOT_AVAILABLE
            if row["minimum"] is None
            else f"{show(row['minimum'])} to {show(row['maximum'])}"
        ),
    }


def _spread(value: object, unit: str) -> str:
    """a standard deviation, unsigned, in the measure's unit."""
    if unit == "minutes":
        return _number(value)
    return f"{float(str(value)) * PERCENT:.1f} pp" if unit == "points" else percent(value)


def _first_only(rows: list[Row], key: str) -> list[Row]:
    """blank a cell that repeats the one above it, so a long label shows once per block."""
    shown: list[Row] = []
    for index, row in enumerate(rows):
        repeat = index > 0 and row[key] == rows[index - 1][key]
        shown.append(row | {key: ""} if repeat else row)
    return shown


def _population(name: object) -> str:
    return POPULATIONS.get(str(name), str(name))


def _count(value: object) -> str:
    return f"{int(str(value)):,}"


def _with_interval(value: object, low: object, high: object) -> str:
    shown = percent(value)
    return shown if low is None or high is None else f"{shown} {interval(low, high)}"


def _level(alpha: object) -> str:
    """an error level as a whole percentage, e.g. 5%."""
    return f"{float(str(alpha)) * PERCENT:.0f}%"


def _number(value: object) -> str:
    return NOT_AVAILABLE if value is None else f"{float(str(value)):.1f}"


def _yes(value: object) -> str:
    return "yes" if str(value).lower() == "true" else "no"


def _text(value: str) -> str:
    return value.replace("_", r"\_")
