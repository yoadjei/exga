"""the spec 11.2 figures, drawn from the experiment tables (ADR 0011).

colours come from the validated reference palette: models take categorical slots 1-3 in fixed
order (all-pairs colour-blind safe), error levels an ordinal blue ramp. every series is also
named at its end and in a legend, so identity never rests on colour alone; text uses ink, not
series colours. one y-axis per chart: two measures get two panels.
"""

import math
from collections.abc import Sequence
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")  # files only; no window
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator, PercentFormatter

from exga.experiment import ALL_FIELDS, Row, Tables

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
mpl.rcParams.update(
    {
        # bundled with matplotlib, so figures render the same on every system
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.titlesize": 10,
    }
)


def draw(tables: Tables, primary_variant: str, folder: Path) -> list[Path]:
    """draw every figure into folder and return their paths.

    raises ValueError for more than three models, which colour alone cannot keep apart.
    """
    folder.mkdir(parents=True, exist_ok=True)
    main = [
        row
        for row in tables.by_group
        if row["variant"] == primary_variant and row["group"] == ALL_FIELDS
    ]
    models = list(dict.fromkeys(str(row["model"]) for row in main))
    if len(models) > len(MODEL_COLOURS):
        raise ValueError(f"figures compare at most {len(MODEL_COLOURS)} models, got {len(models)}")
    paths = [
        _by_alpha(
            main,
            models,
            "mean_acceptance_rate",
            "Share of values accepted without checking",
            folder / "acceptance_vs_alpha.png",
        ),
        _by_alpha(
            main,
            models,
            "mean_realised_error",
            "Error among accepted values",
            folder / "realised_vs_target_error.png",
            target=True,
        ),
    ]
    for model in models:
        rows = [row for row in tables.updating if row["model"] == model]
        if rows:
            paths.append(_updating(rows, model, folder / f"updating_{model}.png"))
    return paths


def _by_alpha(
    rows: Sequence[Row],
    models: Sequence[str],
    column: str,
    title: str,
    path: Path,
    *,
    target: bool = False,
) -> Path:
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
    return _save(figure, path)


def _updating(rows: Sequence[Row], model: str, path: Path) -> Path:
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
    return _save(figure, path)


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


def _style(axes: Axes, title: str, xlabel: str, ylabel: str) -> None:
    axes.set_facecolor(SURFACE)
    axes.set_title(title, color=INK, loc="left")
    axes.set_xlabel(xlabel, color=SECONDARY)
    axes.set_ylabel(ylabel, color=SECONDARY)
    # ticks only at whole percentages, so no label is rounded (2.5% shown as "2%")
    axes.yaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 5, 10]))
    axes.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    axes.set_ylim(bottom=0, top=max(axes.get_ylim()[1], 0.05))
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


def _save(figure: Figure, path: Path) -> Path:
    figure.patch.set_facecolor(SURFACE)
    figure.tight_layout()
    figure.savefig(path, dpi=DPI, facecolor=SURFACE)
    plt.close(figure)
    return path


def _number(value: object) -> float:
    """a table cell as a float; an undefined value (None) is NaN, which matplotlib skips."""
    return math.nan if value is None else float(str(value))
