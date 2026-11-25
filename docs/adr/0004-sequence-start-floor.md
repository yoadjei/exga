# ADR 0004: start testing at the smallest certifiable sample size

- **Status:** accepted; amends spec 5.3 and resolves the open point in ADR 0001
- **Date:** 2026-11-25
- **Code:** `calibrate.start_floor`, `calibrate.fit_threshold`

## Context

Spec 5.3 skips thresholds that accept fewer than m_min = 10 calibration items, then stops at the
first threshold whose test fails. But a binomial test can only pass with at least
required_n(α, δ, 0) items: 45 at α = 0.05, 22 at α = 0.10 (spec 5.4a). Read literally, the first
tested threshold accepts about 10 items, cannot pass whatever its labels, and ends the sequence.
Even a perfect calibration set with distinct scores then comes out NOT_CERTIFIABLE. The test
`test_thresholds_too_small_to_certify_are_skipped_rather_than_ending_the_sequence` shows this
for the spec's own "all correct" edge case.

## Options

| Option | Validity | Power | Verdict |
|---|---|---|---|
| Spec as written (skip below 10) | as below | almost none at α ≤ 0.2 | rejected: the tool would never certify |
| Pure fixed sequence, no skipping | textbook | none: the strictest thresholds accept no items and fail first | rejected |
| Start at a fixed threshold chosen in advance (e.g. 0.9) | textbook | depends on luck: too high and it fails at once, too low and it gives away acceptance | rejected |
| Split the calibration set: choose the start on one half, test on the other | textbook | half the data | rejected: the owner's set has about 40 calibration papers per field |
| **Skip thresholds accepting fewer than max(m_min, required_n(α, δ, 0)) items** | see below | good | **chosen** |

## Decision

Test a threshold only when it accepts at least `start_floor = max(m_min, required_n(α, δ, 0))`
calibration items. The skipped thresholds are exactly those that no labelling could certify,
so they carry no information. The floor depends on the scores only, never on the labels.
`min_accepted` stays as a setting that can raise the floor, for example to tolerate an early
error, provided it is chosen before the calibration data are seen (on the training split).

**Validity.** The floor makes where the sequence starts depend on the scores. When
P(wrong | s) does not increase with s (higher scores are no more often wrong), the guarantee
still holds. The proof is in `docs/method.md`: conditioning on the start position can only make
the first tested null look worse, never better. For curves that break this assumption, the
simulation includes two adversarial non-monotone populations. Over 30 configurations
(`results/guarantee_simulation.csv`, 1,000 repetitions each), the largest violation rate is
0.086 against δ = 0.1.

## Consequences

- At default settings the procedure can certify. In the simulation, 53–100% of runs certify at
  α = 0.10 for the three populations whose errors fall with the score.
- Spec 0A.4's property "adding a correct high-score record never removes certification" does
  not hold. The new record can lift a skipped threshold to the floor, where an error already
  among the top items fails the first test
  (`test_adding_a_correct_top_record_can_remove_certification`). The property that does hold
  is tested instead: correcting a wrong label never removes certification and never raises λ̂.
- An error among the top `start_floor` items still ends the sequence. This is the power cost
  named in ADR 0001, now confined to the top of the score range.

## Revisit if

- `make verify-guarantee` ever reports a violation rate above δ + 0.02.
- Real score distributions show frequent early errors; then compare a floor that allows one
  error, chosen on the training split.
