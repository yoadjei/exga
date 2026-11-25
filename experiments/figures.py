"""the figures of the experiments (spec 11.2, ADR 0011) and the thesis (ADR 0013).

colours come from the validated reference palette: models, and the two task orders of the
user study, take categorical slots 1-3 in fixed order (all-pairs colour-blind safe); error
levels an ordinal blue ramp. every series is also named at its end or in a legend, so
identity never rests on colour alone; text uses ink, not series colours. one y-axis per
chart: two measures get two panels.
"""

import math
import statistics
import textwrap
from collections.abc import Sequence
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")  # files only; no window
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator, PercentFormatter

from exga.experiment import ALL_FIELDS, Tables
from exga.tables import Row
from exga.thesis import POPULATIONS

MODEL_COLOURS = ("#2a78d6", "#eb6834", "#1baf7a")
"""categorical slots 1-3: blue, orange, aqua; validated all-pairs (CVD dE >= 9.2)."""
ALPHA_COLOURS = ("#86b6ef", "#2a78d6", "#104281")
"""ordinal blue steps 250, 450, 650, light to dark for strict to loose error levels."""
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
DPI = 150
LABEL_GAP = 10.0
"""least vertical distance between two end labels, in points."""
LINE_WIDTH = 1.5
DATA_LAYER = 3
"""series draw above the axis spines (layer 2.5), and unclipped, so a value of 0 stays visible."""
ALPHA = r"$\alpha$"
"""the error level's symbol, drawn by matplotlib's mathtext in the figure font."""
DELTA = r"$\delta$"
SIZE_MARKERS = ("o", "D")
"""marker shapes for the calibration set sizes of the guarantee simulation, small to large."""
mpl.rcParams.update(
    {
        # bundled with matplotlib, so figures render the same on every system
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 10,
    }
)


def draw(
    tables: Tables, primary_variant: str, folder: Path, formats: Sequence[str] = ("png",)
) -> list[Path]:
    """draw every experiment figure into folder, once per format, and return the paths.

    raises ValueError for more than three models, which colour alone cannot keep apart.
    """
    main = [
        row
        for row in tables.by_group
        if row["variant"] == primary_variant and row["group"] == ALL_FIELDS
    ]
    models = list(dict.fromkeys(str(row["model"]) for row in main))
    if len(models) > len(MODEL_COLOURS):
        raise ValueError(f"figures compare at most {len(MODEL_COLOURS)} models, got {len(models)}")
    figures = {
        "acceptance_vs_alpha": _by_alpha(
            main, models, "mean_acceptance_rate", "Share of values accepted without checking"
        ),
        "realised_vs_target_error": _by_alpha(
            main, models, "mean_realised_error", "Error among accepted values", target=True
        ),
    }
    for model in models:
        rows = [row for row in tables.updating if row["model"] == model]
        if rows:
            figures[f"updating_{model}"] = _updating(rows, model)
    return [
        path for name, figure in figures.items() for path in _save(figure, folder / name, formats)
    ]


def validity(rows: Sequence[Row], folder: Path, formats: Sequence[str] = ("png",)) -> list[Path]:
    """the guarantee simulation (results/guarantee_simulation.csv): for each population, how
    often a certified threshold broke alpha, against delta."""
    populations = list(dict.fromkeys(str(row["population"]) for row in rows))
    alphas = sorted({_number(row["alpha"]) for row in rows})
    sizes = sorted({int(str(row["n_cal"])) for row in rows})
    delta = _number(rows[0]["delta"])
    figure, axes = plt.subplots(figsize=(6.6, 4.6))
    combinations = [(alpha, size) for alpha in alphas for size in sizes]
    # each (alpha, size) gets its own height within a population, so equal values stay apart
    offsets = [0.6 * (index / (len(combinations) - 1) - 0.5) for index in range(len(combinations))]
    for level, population in enumerate(populations):
        y = len(populations) - 1 - level
        for (alpha, size), offset in zip(combinations, offsets, strict=True):
            [row] = [
                row
                for row in rows
                if row["population"] == population
                and _number(row["alpha"]) == alpha
                and int(str(row["n_cal"])) == size
            ]
            axes.plot(
                _number(row["violation_rate"]),
                y + offset,
                marker=SIZE_MARKERS[sizes.index(size)],
                markersize=6,
                linestyle="none",
                color=ALPHA_COLOURS[alphas.index(alpha)],
                zorder=DATA_LAYER,
                clip_on=False,
            )
    axes.axvline(delta, color=MUTED, linestyle="--", linewidth=1.2)
    axes.annotate(
        f"{DELTA} = {delta:.0%}",
        (delta, len(populations) - 0.5),
        xytext=(4, 0),
        textcoords="offset points",
        color=SECONDARY,
        fontsize=8,
    )
    axes.set_yticks(range(len(populations)))
    axes.set_yticklabels([textwrap.fill(POPULATIONS.get(p, p), 30) for p in reversed(populations)])
    axes.set_ylim(-0.6, len(populations) - 0.4)
    _style(
        axes,
        f"Certified thresholds whose true error is above {ALPHA}",
        "Share of 1,000 calibration sets",
        "",
        percent=False,
    )
    axes.grid(axis="y", visible=False)
    axes.grid(axis="x", color=GRID, linewidth=0.6)
    axes.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    axes.set_xlim(0, max(delta * 1.25, axes.get_xlim()[1]))
    handles = [
        Line2D([], [], marker="o", linestyle="none", color=colour, label=f"{ALPHA} = {alpha:.0%}")
        for alpha, colour in zip(alphas, ALPHA_COLOURS, strict=False)
    ] + [
        Line2D([], [], marker=marker, linestyle="none", color=MUTED, label=f"{size:,} items")
        for size, marker in zip(sizes, SIZE_MARKERS, strict=False)
    ]
    axes.legend(handles=handles, frameon=False, labelcolor=SECONDARY, loc="lower right", fontsize=8)
    return _save(figure, folder / "guarantee_validity", formats)


def study_times(rows: Sequence[Row], folder: Path, formats: Sequence[str] = ("png",)) -> list[Path]:
    """the user study (results/study/participants.csv): each participant's minutes by hand and
    with exga, coloured by which task came first, with the median of each task."""
    figure, axes = plt.subplots(figsize=(4.4, 3.6))
    orders = {"manual": "by hand first", "tool": "exga first"}
    for (first, label), colour in zip(orders.items(), MODEL_COLOURS, strict=False):
        mine = [row for row in rows if row["first_condition"] == first]
        for index, row in enumerate(mine):
            axes.plot(
                [0, 1],
                [_number(row["manual_minutes"]), _number(row["tool_minutes"])],
                marker="o",
                markersize=6,
                linewidth=LINE_WIDTH,
                color=colour,
                label=label if index == 0 else None,
                zorder=DATA_LAYER,
                clip_on=False,
            )
    for x, column in enumerate(("manual_minutes", "tool_minutes")):
        values = [_number(row[column]) for row in rows]
        if values:
            axes.plot(
                x,
                statistics.median(values),
                marker="_",
                markersize=28,
                markeredgewidth=2.5,
                color=INK,
                linestyle="none",
                label="median" if x == 0 else None,
                zorder=DATA_LAYER + 1,
            )
    _style(axes, "Minutes per task, one line per participant", "", "Minutes", percent=False)
    axes.set_xticks([0, 1])
    axes.set_xticklabels(["By hand", "With exga"])
    axes.set_xlim(-0.3, 1.3)
    _legend(axes)
    return _save(figure, folder / "study_times", formats)


def _by_alpha(
    rows: Sequence[Row],
    models: Sequence[str],
    column: str,
    title: str,
    *,
    target: bool = False,
) -> Figure:
    figure, axes = plt.subplots(figsize=(5.2, 3.4))
    alphas = sorted({_number(row["alpha"]) for row in rows})
    if target:
        axes.plot(
            alphas, alphas, linestyle="--", linewidth=1.2, color=MUTED, label=f"target (= {ALPHA})"
        )
    ends: list[tuple[list[float], list[float], str]] = []
    for model, colour in zip(models, MODEL_COLOURS, strict=False):
        mine = sorted(
            (row for row in rows if row["model"] == model), key=lambda r: _number(r["alpha"])
        )
        xs = [_number(row["alpha"]) for row in mine]
        ys = [_number(row[column]) for row in mine]
        _series(axes, xs, ys, colour, model, marker="o")
        ends.append((xs, ys, model))
    _style(axes, title, f"Target error level {ALPHA}", "Mean over splits")
    axes.set_xticks(alphas)
    axes.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    _legend(axes)
    _end_labels(axes, ends)
    return figure


def _updating(rows: Sequence[Row], model: str) -> Figure:
    figure, (left, right) = plt.subplots(1, 2, figsize=(8.4, 3.2), sharex=True)
    alphas = sorted({_number(row["alpha"]) for row in rows})
    panels = ((left, "mean_acceptance_rate"), (right, "mean_realised_error"))
    ends: dict[str, list[tuple[list[float], list[float], str]]] = {c: [] for _, c in panels}
    for alpha, colour in zip(alphas, ALPHA_COLOURS, strict=False):
        mine = sorted(
            (row for row in rows if _number(row["alpha"]) == alpha),
            key=lambda r: _number(r["audit_records"]),
        )
        xs = [_number(row["audit_records"]) for row in mine]
        label = f"{ALPHA} = {alpha:.0%}"
        for axes, column in panels:
            ys = [_number(row[column]) for row in mine]
            _series(axes, xs, ys, colour, label)
            ends[column].append((xs, ys, label))
    _style(left, f"{model}: share accepted", "Audit records", "Mean over splits")
    _style(right, f"{model}: error among accepted", "Audit records", "Mean over splits")
    _legend(left)
    for axes, column in panels:
        _end_labels(axes, ends[column])
    return figure


def _series(
    axes: Axes,
    xs: Sequence[float],
    ys: Sequence[float],
    colour: str,
    label: str,
    marker: str | None = None,
) -> None:
    axes.plot(
        xs,
        ys,
        marker=marker,
        markersize=6,
        linewidth=LINE_WIDTH,
        color=colour,
        label=label,
        zorder=DATA_LAYER,
        clip_on=False,
    )


def _style(axes: Axes, title: str, xlabel: str, ylabel: str, *, percent: bool = True) -> None:
    """recessive chrome; percent puts the y axis in whole percentages from 0."""
    axes.set_facecolor(SURFACE)
    axes.set_title(title, color=INK, loc="left")
    axes.set_xlabel(xlabel, color=SECONDARY)
    axes.set_ylabel(ylabel, color=SECONDARY)
    if percent:
        # ticks only at whole percentages, so no label is rounded (2.5% shown as "2%")
        axes.yaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 5, 10]))
        axes.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
        axes.set_ylim(bottom=0, top=max(axes.get_ylim()[1], 0.05))
    elif ylabel:
        axes.set_ylim(bottom=0)
    axes.grid(axis="y", color=GRID, linewidth=0.6)
    axes.set_axisbelow(True)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(BASELINE)
    axes.tick_params(colors=MUTED, labelcolor=SECONDARY)


def _legend(axes: Axes) -> None:
    """a legend for two or more series; a lone series is named by its end label and the title."""
    if len(axes.get_legend_handles_labels()[0]) > 1:
        axes.legend(frameon=False, labelcolor=SECONDARY, loc="best")


def _end_labels(axes: Axes, series: Sequence[tuple[Sequence[float], Sequence[float], str]]) -> None:
    """name each series at its last defined point, moved apart so no two labels overlap."""
    ends = []
    for xs, ys, text in series:
        points = [(x, y) for x, y in zip(xs, ys, strict=True) if not math.isnan(y)]
        if points:
            ends.append((*points[-1], text))
    figure = axes.get_figure()
    if not ends or figure is None:
        return
    figure.canvas.draw()  # data-to-display transforms need a laid-out figure
    to_points = 72 / figure.dpi
    above = -math.inf
    for x, y, text in sorted(ends, key=lambda end: end[1]):
        height = float(axes.transData.transform((x, y))[1]) * to_points
        offset = max(0.0, above + LABEL_GAP - height)
        axes.annotate(
            text,
            (x, y),
            xytext=(7, offset),  # clear of a 6 pt marker
            textcoords="offset points",
            va="center",
            color=SECONDARY,
            fontsize=8,
        )
        above = height + offset


def _save(figure: Figure, stem: Path, formats: Sequence[str]) -> list[Path]:
    """write figure as stem.<format> for each format (png, pdf, ...) and close it."""
    stem.parent.mkdir(parents=True, exist_ok=True)
    figure.patch.set_facecolor(SURFACE)
    figure.tight_layout()
    paths = [stem.with_suffix(f".{extension}") for extension in formats]
    for path in paths:
        figure.savefig(path, dpi=DPI, facecolor=SURFACE)
    plt.close(figure)
    return paths


def _number(value: object) -> float:
    """a table cell as a float; an undefined value (None) is NaN, which matplotlib skips."""
    return math.nan if value is None else float(str(value))
