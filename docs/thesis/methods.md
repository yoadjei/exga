# Chapter 3 support: the method, with sources

> **What this page is.** The facts chapter 3 (Methodology, spec 15) needs, in the chapter's
> order, each with the file it comes from. It is reference material for the owner, not
> thesis text. Write the chapter in your own words, under your institution's rules on
> AI-assisted writing. Numbers are from committed files or from `make thesis`. If code or
> results change, rebuild them and check the numbers here again.

## 3.1 System overview

exga is a Python library with a local web app built on it (ADR 0010). One run takes a folder
of PDF papers and a list of fields, and goes through seven steps.

1. **Read.** PyMuPDF reads each PDF's text layer in block order (`exga/pdf.py`,
   `exga/document.py`). A PDF with fewer than 200 extractable characters is treated as
   scanned and refused; there is no OCR. Long papers are split into chunks of at most 24,000
   tokens (`ExtractionSettings.max_chunk_tokens`).
2. **Extract.** For each paper and field, the model gives one greedy answer at temperature 0
   and five sampled answers at temperature 0.7 (`ExtractionSettings`). Each answer is JSON
   with a value (null for "not reported"), an evidence quote and a page. An answer that
   does not parse gets one repair request at temperature 0. For a paper in several chunks,
   each answer takes, in order of preference:
   - the first chunk's value whose evidence is found in that chunk;
   - otherwise the first value;
   - otherwise "not reported" (`extract.merge_chunks`).
   Models are reached through one OpenAI-compatible chat-completions client, hosted or
   local (vLLM, llama.cpp), because the method needs token log-probabilities and a set
   temperature (ADR 0006). Responses are cached, and a budget limits spending.
3. **Score.** Three signals in [0, 1] describe how far to trust the greedy value (spec 7.4,
   `exga/score.py`):
   - *agreement*: the share of the five sampled values that match the greedy value under
     the field's correctness rule;
   - *token probability*: the geometric mean of the greedy value's token probabilities,
     exp(mean token log-probability);
   - *evidence check*: 1 when the quote is found in the paper and the text found states the
     value; 0.5 when it is found but does not state the value; 0 when it is not found.

   The score is their weighted average, with equal weights (ADR 0007). A signal that does
   not exist drops out of the average: a "not reported" answer has no evidence check, and
   a model without log-probabilities has no token probability. An item without a usable
   greedy answer scores 0.
4. **Calibrate.** Each field gets a threshold λ̂ from checked values (section 3.4).
5. **Decide.** A value is *Accepted* when its score is at least λ̂, and *Check* otherwise.
   A field with no certified threshold is *Not certifiable*, and every value in it is
   checked (`exga/decide.py`, `exga/messages.py`).
6. **Review.** The app shows each value with its evidence highlighted on the PDF page. A
   person can correct values and export the results (pages Fields, Run, Calibrate, Review,
   Audit, Export; ADR 0010).
7. **Audit and update.** A uniform random sample of the extracted values is checked, and the
   thresholds are recomputed from those checks only (section 3.5).

The app serves the computer it runs on only, without usage statistics. Paper text leaves the
computer only when the model is a hosted service, and the app asks for consent first
(ADR 0010).

## 3.2 Correctness rules

One function decides whether an extracted value is right, `matching.is_correct` (spec 6.4,
ADR 0003). The same rule labels calibration data, compares sampled answers for the agreement
signal (`matching.values_match`) and scores the experiments. "Not reported" matches only
"not reported". Otherwise, the rule depends on the field's group:

- **numeric:** the first number in the value, read as a decimal, must be within the field's
  tolerance of the gold value. The tolerance is the larger of an absolute and a relative
  tolerance, and both are zero by default. "k", "thousand", "million" and "billion" are
  read; "m" is not.
- **categorical:** after normalising case and punctuation and mapping listed synonyms, the
  value must equal the gold value.
- **short_text:** the same comparison, or a token F1 of at least 0.8.
- **long_text:** a token F1 of at least 0.6.

Known blind spots are ranges, inequalities, decimal commas and differing units
(`docs/limitations.md`). Agreement with a person's judgements has not been measured yet
(spec 13).

## 3.3 Field definitions

A field has a name, a description that must pin exactly one answer per paper (spec 6.3), a
group (numeric, categorical, short_text or long_text) and optional allowed values, units,
tolerances and synonyms (`exga/schemas.py`, `examples/fields.yaml`). Calibration is per field
(ADR 0005).

## 3.4 The statistical guarantee

Source: `docs/method.md`, ADRs 0001, 0004 and 0005.

- **Promise.** For one field, with probability at least 1 − δ over the draw of the
  calibration records, the error rate among accepted values, P(wrong | s ≥ λ̂), is at most α.
  The defaults are α = 0.05 and δ = 0.1. The promise is per field.
- **Assumptions.**
  - Exchangeability: calibration papers and new papers come from one distribution.
  - Independence: each paper gives at most one calibration item per field.
  - Random audits: calibration records are a random sample, not values someone chose to
    check.
  - For the starting floor only, monotone errors: higher scores are not more often wrong.
- **Procedure.** The procedure is fixed-sequence testing in the Learn-then-Test framework
  (Angelopoulos et al., 2025), and works as follows.
  - Thresholds 1.000, 0.995, …, 0.000 are tested from the strictest down.
  - A threshold with fewer accepted calibration items than n₀ = max(10, required_n(α, δ,
    0)) is skipped. n₀ is the fewest items that could certify α even with zero errors.
  - For each threshold tested, p = BinomCDF(errors; accepted, α) is computed. The
    threshold is certified if p ≤ δ. The first failure stops the walk.
  - λ̂ is the last certified threshold.
- **Why it holds.** `docs/method.md` gives the proof, including why skipping sparse
  thresholds keeps the bound when errors are monotone (ADR 0004).
- **Pooling.** A field with fewer records than n₀ takes its field group's pooled result. The
  result is then labelled pooled, because it assumes independence across fields (ADR 0005).
- **Reported with each threshold.** Alongside λ̂, exga reports:
  - the number of calibration records and their raw error rate;
  - the accepted records at λ̂ and their errors;
  - the one-sided Clopper–Pearson upper bound at λ̂, which describes the calibration set
    and is not a second guarantee.
- **Sample sizes.** Table `calibration_sizes` (from `calibrate.required_n`) gives the
  accepted items needed to certify. At δ = 0.1 and α = 0.05, that is 45 with no errors, 77
  with one and 105 with two.

## 3.5 Updating from random audits

Source: ADR 0009, `exga/audit.py`. Each review session, exga draws a uniform random sample
of all extracted items, accepted and flagged alike: 5% of them, and at least 3 items. Only
labels of drawn items become calibration records. Corrections made elsewhere change the
exported data but never enter calibration, because which values people check depends on
what they see. A drawn item may be skipped only when it cannot be checked at all, and skips
are counted. After each completed batch, the thresholds are recomputed and appended to a
versioned threshold log. The claim is about the current threshold only: a long log is
repeated testing (section 3.6).

## 3.6 Checking the guarantee by simulation

Real data cannot confirm the guarantee, because the true error rate is unknown. The method
is therefore checked on simulated populations where it is known (spec 9.2).

- **Guarantee simulation** (`make verify-guarantee`, table `guarantee_simulation`, figure
  `guarantee_validity`).
  - Design: 5 populations × α ∈ {0.05, 0.10, 0.20} × 200 or 1,000 calibration items, with
    1,000 calibration sets each.
  - Populations: three with errors falling as scores rise, and two built to break that
    assumption.
  - Result: in all 30 configurations, the share of calibration sets whose certified
    threshold had a true error above α is within the spec's allowance of δ + 0.02. The
    largest share is 8.6%, for the cubic monotone population at α = 0.20 with 1,000 items
    (`results/guarantee_simulation.csv`).
  - Dropping half of the wrong values from the calibration data raises the share to about
    84% (`tests/test_guarantee_sim.py`, `docs/method.md`).
- **Audit simulation** (table `audit_simulation`).
  - Design: 10 rounds of 400 new items, with 5% of each round audited and the thresholds
    recomputed after each round, at α = δ = 0.1, over 1,000 repetitions.
  - Random audits: 0.0–3.4% of certified threshold versions had a true error above α. In
    up to 12.5% of runs, some version did.
  - Logging wrong values half as often as right ones: up to 45.6% of versions and 82.9% of
    runs (`results/audit_simulation.csv`).

## 3.7 Data

- **Benchmark** (spec 10.1, ADR 0008, table `main_data`).
  - Yun et al. (2024): 699 intervention–comparator–outcome comparisons in 120 reports of
    randomised controlled trials, pinned to commit `1bc768d4` (Apache-2.0).
  - Eight numeric fields: the event counts and group sizes of binary outcomes, and the
    means, standard deviations and group sizes of continuous outcomes.
  - The 10 DEV papers are used for prompt development only.
  - Of the 656 TEST comparisons, 167 have their data in figures or image tables. They are
    left out, because the model reads text only.
  - Each paper gives one comparison per field, drawn at random, so items are independent
    across papers.
  - This leaves 550 items from 88 papers: 88 for each group-size field, 73 for each mean
    and standard deviation, and 41 for each event count. 107 of them are not reported in
    the text (item seed 0).
- **Annotated set** (spec 10.2, `data/annotated/README.md`).
  - 50–100 open-access PDFs from varied disciplines, with the owner's field list.
  - Papers are chosen before any model is run on them, and labelled without seeing model
    output.
  - 20% are labelled again by a second annotator, and per-field agreement is reported
    (`exga check-gold`).
  - Not yet built; owner action 2 in `docs/PROGRESS.md`.

## 3.8 Experiments

Source: ADR 0011; configs in `experiments/*.yaml`.

- **Splits.** Each experiment uses 50 random 30/40/30 splits of papers into training,
  calibration and test sets. The default score has no fitted parameters, so the training
  papers are unused. They are held out so that a fitted score can be added later.
- **Metrics.** Measured on the test papers, per model, field group and α:
  - raw accuracy;
  - the share accepted (the checking saved);
  - the error among accepted values;
  - coverage;
  - whether the field certified.
- **Intervals.** 95% percentile bootstrap over test *papers* (1,000 resamples) on the
  primary split, because items from one paper are not independent. Across all 50 splits,
  the experiments report means, the share of splits that certified, and the share whose
  test error exceeded α.
- **Caveat on that last share.** A test split has at most about 26 items per field, so
  chance alone often puts the observed error above α. The share therefore overstates how
  often the guarantee fails, and validity rests on the simulation (section 3.6).
- **Baselines.** Accept all values; a fixed cut-off of 0.8 on the same score without
  calibration; and check every value.
- **Signal ablation.** Four scores on the same answers: agreement alone, with token
  probability, with the evidence check, and all three. Each is calibrated on its own.
- **Models.** The main config compares a hosted model with an open-weight model served
  locally. The model ids are set when the runs are made (owner action 4).
- **Updating.** Audit batches of 10 items are drawn at random from the calibration papers.
  After each batch the thresholds are recomputed and the test results measured, and the
  curves are averaged over splits.
- **Reproducibility.** Results go to `results/<name>-<hash>/`, where the hash is taken from
  the config. A manifest records the git commit, config, settings, model ids, prompt
  versions, seeds, input hashes and package versions.

## 3.9 User study

Source: ADR 0012; materials in `study/`.

- **Design.** Within-subject, with 5–10 students or researchers. Each extracts the same
  fields from two sets of three annotated papers: one set by hand and one with exga.
- **Counterbalancing.** Four orders cross which condition comes first with which set it
  uses. Every block of four participants gets each order once.
- **Calibration without the study papers.** The researcher prepares one exga project per
  set. Its calibration records come from the annotated-set experiment *without* the six
  study papers.
- **Timing and limits.** The participant's time covers their own work only. Each condition
  stops at 25 minutes, and unanswered items count as wrong.
- **Measures.** Time; accuracy against gold under the same correctness rules; and the share
  of tool values the participant corrected. The Review page records corrections, not
  confirmations.
- **Questionnaire.** After the tool condition: the System Usability Scale (Brooke, 1996)
  and four trust statements written for this study. Each statement is reported on its own.
- **Reporting.** Descriptive only: n, mean, standard deviation, median, quartiles and range,
  also split by which condition came first (tables `user_study` and `trust`, figure
  `study_times`). There is no hypothesis test.
- **Ethics and data.** Informed consent and anonymous ids. Data stay on the researcher's
  machine. Ethics approval is the owner's to obtain.

## 3.10 Implementation and quality assurance

exga is written in Python (3.11 or later) and released as v0.1.0 under the licence in
`LICENSE`, with `CITATION.cff`.

- **Tests.** The test suite covers:
  - the matching rules, the calibration procedure and the simulations;
  - the PDF handling, and extraction with a mock model;
  - every app page;
  - the experiment, study and thesis scripts end to end.
- **Continuous integration.** CI runs ruff, mypy (strict) and the tests on every push. It
  also installs the built package into a clean environment.
- **Where to find the details.** `docs/PROGRESS.md` gives the current test count and
  coverage. The ADRs in `docs/adr/` record each design decision with the options
  considered.

## What the method does not cover

These are stated in `docs/limitations.md`, for chapter 3's scope or chapter 5:

- the exchangeability assumption;
- per-field rather than simultaneous bounds;
- text PDFs in English only;
- correctness rules not yet checked against a person's judgements;
- repeated testing over a long threshold log;
- trust in imported records.

Three items of the spec were not built or run:

- the fitted (logistic) score of spec 7.4;
- the conformal-selection comparison of spec 11.1, question 7, which is optional;
- the 50-judgement validation of the matching rules (spec 13).
