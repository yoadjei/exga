# ADR 0013: how results become thesis tables and figures

- **Status:** accepted 2026-11-25 (the owner delegated this decision; P11 sign-off remains
  the owner's)
- **Date:** 2026-11-25
- **Spec:** sections 0A.9, 11, 12 (P11), 15; code: `exga/thesis.py`, `exga/tables.py`,
  `experiments/thesis.py`, `experiments/figures.py`; text: `docs/thesis/`

## Context

P11 asks for the thesis's tables and figures to be exported, and for a write-up of the method.
Chapter 3 describes the method, and chapter 4 reports validity, efficiency, field types,
ablations, models, updating and the user study (spec 15). Spec 0A.9 requires every
quantitative claim to point to a results file. When this ADR was written, only the two
simulation results existed. The model runs wait for an endpoint, and the user study waits
for ethics approval. Whatever turns results into tables must therefore work before any of
those results exist, and must not invent the missing ones.

## Decisions

1. **One command, from result files only.** `make thesis` (`experiments/thesis.py`) reads
   the simulation CSVs, each experiment's `tables/*.csv` and `results/study/*.csv`, and
   writes `results/thesis/`. It computes only two things itself, and neither is a result:
   the calibration-size table, from `calibrate.required_n`, and each dataset's item
   counts, from the items the experiments load. When a source is missing, the export skips
   it and names the command that would produce it. Nothing is filled in.
2. **Two formats for each output.**
   - Tables are written as booktabs LaTeX, for `\input`, and as a CSV of the same
     displayed cells, for a word processor or for checking.
   - Figures are written as PDF (vector, for LaTeX) and as PNG (for a word processor or
     slides).
   - Numbers are formatted once, in `exga/thesis.py`, so the LaTeX and the CSV agree.
3. **Number formats.**
   - Rates are percentages with one decimal, and the column header carries the unit,
     "(%)".
   - Differences of rates are signed percentage points (pp).
   - α and δ are written as decimals (0.05), as in `docs/method.md`.
   - Counts have thousands separators.
   - Intervals and quartiles are written [low, high].
   - A value that does not exist is "n/a", for example the error among accepted values
     when nothing was accepted.
4. **Every table fits a portrait A4 page.** Each table was compiled with pdflatex on A4 with
   2.5 cm margins, including worst-case names and values, and checked for overfull boxes.
   To make them fit:
   - Tables are set in `\small` with 4 pt column gaps, and long headers take two or three
     lines.
   - Long text wraps ragged right. The tables therefore need
     `\usepackage{booktabs,array}`.
   - The main results table has one table per model. With a model column it was too wide.
   - The main results table gives a 95% interval for the error among accepted values
     only, as spec 11.2 asks. The acceptance intervals stay in each experiment's
     `by_group.csv`.
5. **The tables** (`<experiment>` is the config's name, `<model>` a model's name):
   - `calibration_sizes`;
   - `guarantee_simulation` and `audit_simulation`;
   - `<experiment>_data`, once per dataset;
   - `<experiment>_results_<model>`, `<experiment>_fields_<model>` and
     `<experiment>_baselines`, for an experiment with one score;
   - `<experiment>_ablation`, for one with several scores;
   - `user_study` and `trust`.

   **The figures:**
   - `guarantee_validity` and `study_times`;
   - for each experiment, `acceptance_vs_alpha`, `realised_vs_target_error` and
     `updating_<model>`.
6. **Not committed.** `results/thesis/` is ignored by git. It is rebuilt by one command, and
   its study tables derive from `results/study/`, which stays on the researcher's machine
   (ADR 0012). Publishing study summaries with the thesis is the owner's decision.
7. **Support text, not thesis text.** `docs/thesis/methods.md` gives chapter 3's facts in
   order, each with its source. `docs/thesis/results_guide.md` says which output answers
   each question of spec 11.1, and the caveat to report with it. Neither is meant to be
   pasted into the thesis. The thesis is written by the owner, under the institution's
   rules on AI-assisted writing.
8. **Question 7 of spec 11.1** (the default method against conformal selection) is
   optional and was not run, so it has no table. The results guide says so.

## Consequences

- Once the real runs finish, `make experiments` followed by `make thesis` produces every
  chapter 4 table and figure, with no hand-copied numbers.
- A table appears only for a source that exists. A thesis draft written before the runs
  has gaps where results are missing, and the export lists those gaps.
- With one results table per model, a reader compares models across two tables. The
  acceptance-vs-α figure shows both models together.
- Changing a format means changing `exga/thesis.py` and its tests (`tests/test_thesis.py`).
  The end-to-end test (`tests/test_thesis_run.py`) checks which files the export writes.
