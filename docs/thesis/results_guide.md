# Chapter 4 support: which output answers which question

> **What this page is.** It maps each question of spec 11.1 to the tables and figures that
> `make thesis` writes, and gives the caveat to report with each. It is reference material
> for the owner, not thesis text. When this page was written, only the two simulations had
> been run. Model results and study data do not exist yet, and nothing here states or
> predicts them.

## Building the outputs

| Step | Command | Produces | Status |
|---|---|---|---|
| 1 | `make verify-guarantee` | `results/guarantee_simulation.csv`, `results/audit_simulation.csv` | done, committed |
| 2 | `make experiments` | `results/<name>-<hash>/` for `main`, `ablations` and `annotated` | waits for owner actions 2 and 4 (`docs/PROGRESS.md`) |
| 3 | `python study/study.py analyse` | `results/study/` | waits for owner action 5 |
| 4 | `make thesis` | `results/thesis/tables/*.tex`, `*.csv` and `results/thesis/figures/**/*.pdf`, `*.png` | can run at any time |

`make thesis` lists every source it skipped, with the command that produces it. Run it again
after each step. If the settings were changed with `--env-file` for the experiments, pass
the same file to `make thesis` (`python experiments/thesis.py --env-file .env`), so the
data tables read the papers the same way.

## Using the outputs

- **LaTeX.** Add `\usepackage{booktabs,array,graphicx}` to the preamble. Each table is a
  complete float labelled `tab:<file name>`. For example:

  ```latex
  \input{results/thesis/tables/main_results_hosted.tex}
  % ... as Table~\ref{tab:main_results_hosted} shows ...
  \begin{figure}
    \centering
    \includegraphics[width=\linewidth]{results/thesis/figures/guarantee_validity.pdf}
    \caption{...}
  \end{figure}
  ```

- **Word or other editors.** Each table's CSV holds the same cells as its LaTeX version,
  and each figure is also a PNG.
- **Figures.** Each figure has a short title, but no caption or source. The thesis caption
  should say what is plotted and name the results file.
- **Format conventions.** All tables follow the same conventions (ADR 0013):
  - rates are percentages, with "(%)" in the column header;
  - differences are signed, in percentage points;
  - α is written as a decimal;
  - "n/a" marks a value that does not exist, such as the error among accepted values when
    nothing was accepted.

## Questions (spec 11.1) and their outputs

File names below are for the configs in `experiments/`: `main`, `ablations` and `annotated`.
Each annotated-set table has the same form as its `main_` counterpart.

### 1. Validity: is realised error at most α, and is the violation rate at most δ?

- **Answered by:**
  - `guarantee_simulation` (table) and `guarantee_validity` (figure): the share of 1,000
    calibration sets whose certified threshold had a true error above α, for 30
    configurations;
  - `main_results_<model>`, column "Test error above α", and `main/realised_vs_target_error`
    (figure), for the real data.
- **What exists now:** the simulation. All 30 configurations are within δ + 0.02, and the
  largest share is 8.6% against δ = 0.1 (`results/guarantee_simulation.csv`).
- **Caveat:** validity is shown by the simulation, where the true error is known. On real
  data a test split has at most about 26 items per field, so chance alone often puts the
  observed error above α. The "test error above α" share therefore overstates how often
  the guarantee fails (ADR 0011, decision 4). Each table's note says so; the text should
  too.

### 2. Efficiency: what share is accepted, against the baselines?

- **Answered by:**
  - `main_results_<model>`, column "Accepted": the share of values that need no check;
  - `main_baselines`: accept all, a fixed cut-off of 0.8, check all;
  - `main/acceptance_vs_alpha` (figure).
- **Caveat:** the baselines carry no guarantee. "Accept all" has an error equal to
  1 − raw accuracy. The fixed cut-off can accept more values or fewer than the
  calibrated threshold, but its error is not controlled. Compare acceptance at the same
  error level, not acceptance alone.

### 3. Field types: which groups certify, and at what acceptance rate?

- **Answered by:**
  - `main_results_<model>`, one block per field group;
  - `main_fields_<model>`: certified share, mean acceptance and raw accuracy per field;
  - `main_data`: the items per field.
- **Caveat:** on the benchmark, a field has about 35 calibration items or fewer (16 for
  event counts), and certifying α = 0.10 needs at least 22 accepted items with no errors
  (`calibration_sizes`). Fields that do not certify at small α are an expected result to
  report, not a defect (spec 13, Kotte 2026). The benchmark has numeric fields only, so the
  other field groups come from the annotated set.

### 4. Signals ablation

- **Answered by:** `ablations_ablation`. It covers four scores on the same answers
  (agreement alone, with token probability, with the evidence check, all three), each
  calibrated on its own, as means over 50 splits.
- **Caveat:** the variants reweight stored signals, so their differences reflect the score
  alone. With these item counts, small differences between variants may be noise; say so
  unless they are consistent across error levels.

### 5. Models: hosted against open-weight

- **Answered by:** `main_results_hosted` beside `main_results_open-weight` (one table per
  model, ADR 0013), `main_fields_<model>`, and `main/acceptance_vs_alpha`, which shows both
  models.
- **Caveat:** name each model's id and the date of the run (both are in the manifest).
  Hosted models change over time.

### 6. Updating: acceptance and error as audits accumulate

- **Answered by:** `main/updating_<model>` (figure): acceptance and realised error after
  each audit batch of 10, averaged over splits, one line per α.
- **Also relevant:** `audit_simulation` (table) shows why only random audits enter
  calibration. The simulation's numbers are in `docs/thesis/methods.md`, section 3.6.
- **Caveat:** early batches are too small to certify anything, so acceptance starts at 0.
  The curve shows when enough records exist, not a guarantee for each point.

### 7. Optional: the default method against conformal selection

Not run. Spec 11.1 marks this question optional, and no table or figure exists for it
(ADR 0013).

### User study (spec 11.3)

- **Answered by:**
  - `user_study` (table): time, accuracy, their within-person differences, the share of
    values corrected with exga and the SUS score, also by which task came first;
  - `trust` (table): answer counts for each statement;
  - `study_times` (figure): each participant's minutes by hand and with exga.
- **Caveats** (ADR 0012):
  - The report is descriptive only, with no hypothesis tests.
  - The results describe these participants and papers, not tools in general.
  - The trust statements are not a validated scale, so they are reported one by one.
  - The tool condition counts corrections, not checks.
  - If no field certified in the study projects, the comparison is checking with evidence
    against extracting from scratch, and the text must say so.

## Before quoting a number

- It comes from a file under `results/`. That file's `manifest.json` names a commit, and
  shows the working tree was not dirty.
- The text states α, δ, the dataset, the model id, the number of splits, and that the
  guarantee is per field.
- An interval or spread is reported with every estimate where the table has one.
