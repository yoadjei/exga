# ADR 0011: how the experiments measure validity and efficiency

- **Status:** accepted 2026-11-25 (the owner delegated this decision)
- **Date:** 2026-11-25
- **Spec:** sections 7.8, 10.3, 11; code: `exga/evaluate.py`, `exga/experiment.py`,
  `experiments/`

## Context

Spec 11 asks five questions of real extractions: is the realised error at most α, how often
is the guarantee violated, how much verification is saved against baselines, which field
groups certify, and what each confidence signal adds. The answers go into the thesis, so
every number must be reproducible from a config, and every choice that could flatter the
method must be fixed before results exist. No results exist yet: this ADR is written before
any model run.

## Decisions

1. **Unit and splits.** An item is one (paper, field) of the benchmark's TEST split
   (ADR 0008). Papers are split 30/40/30 into train, calibration and test (spec 10.3), with
   50 seeds. The default score has no fitted parameters, so train papers are unused in the
   main experiment; they are kept out so a fitted score (spec 7.4, should-have) can be added
   without changing the other splits.
2. **Metrics on the test papers,** per model, field group and α: items; raw accuracy (share
   of all values that are right); acceptance rate (share accepted, the verification saved);
   realised error (wrong among accepted, undefined when nothing is accepted); coverage (share
   of right values that were accepted). Each is computed per field and pooled per group.
3. **Intervals.** 95% percentile bootstrap over test **papers**, 1,000 resamples, seeded:
   items from one paper share a text and a model reading, so they are not independent, and
   resampling items would make intervals too narrow. An interval belongs to one split, so
   tables give the point estimate and interval of the primary split (seed 0), and, across
   all 50 splits, the mean, the share of splits in which the unit certified, and the rate
   in decision 4.
4. **Violations, and their caveat.** For each split and certified unit, a violation is a
   realised test error above α. A test set of about 26 papers has about 26 items per field,
   so sampling noise alone pushes realised error above α often, even when the true error is
   just below it. This rate therefore overstates how often the guarantee fails. It is
   reported under the name "test error above α", next to the mean realised error. The
   guarantee itself is validated by the simulation of P1, where the true error is known.
5. **Baselines** on the same test items: accept all (no checking), a fixed cut-off of 0.8 on
   the same score without calibration, and verify all (acceptance 0, error 0).
6. **Signal ablation** (spec 11.1.4): agreement only; agreement and token probability;
   agreement and evidence check; all three. Each variant is a reweighting of the stored
   signals (`ScoreSettings`), so no extraction is repeated, and each is calibrated on its
   own. Comparing variants is an experiment, not a deployed claim, so this is not the
   repeated testing of ADR 0009.
7. **Updating curve** (spec 11.1.6): per split, start with no records, draw audit batches
   uniformly without replacement from the calibration papers' items, recalibrate after each
   batch on all audit records so far, and measure acceptance and realised error on the test
   papers. Curves are averaged over splits.
8. **Outputs** go to `results/<name>-<hash>/`: `manifest.json`, `tables/*.csv` and
   `figures/*.png`. The hash is the first 8 hex digits of the sha256 of the validated
   config, so a changed config never overwrites earlier results.
9. **Manifest** (spec 0A.5): git commit and whether the tree was dirty, the config, the
   settings, model ids, prompt versions, seeds, the benchmark's commit and annotation hash,
   the sha256 of every input file, and Python and package versions.
10. **Figures** use matplotlib, a development dependency only: experiments run from the
    repository, and the installed package never draws.

## Consequences

- Real results need extractions from a model endpoint; until the owner runs
  `experiments/run.py extract`, the pipeline is tested on mock extractions only, and no
  result is reported.
- The violation rate on real data cannot confirm the guarantee by itself (decision 4); the
  thesis cites the simulation for validity and the real data for efficiency.
