# ADR 0001: certify thresholds with fixed-sequence binomial testing

- **Status:** accepted 2026-11-25 (the owner delegated these decisions); amended by ADR 0003
- **Date:** 2026-11-25
- **Spec:** sections 2, 5.1–5.5

## Context

A researcher using exga needs to know how many accepted values are wrong. The quantity to
control is the selective error r(λ) = P(wrong | s ≥ λ) among values whose score s clears the
threshold λ. Spec 5.2 promises a high-probability bound: with probability at least 1 − δ over
the calibration draw, r(λ̂) ≤ α. The method must work with any score, with tens of verified
items per field (the owner-annotated set has 50–100 papers), and without assuming that errors
fall smoothly as the score rises.

## Options

| Option | What it bounds | Verdict |
|---|---|---|
| Split conformal prediction | coverage of a prediction set | wrong quantity: says nothing about errors among accepted single values, and free-text fields have no finite label set |
| Conformal risk control (Angelopoulos et al., 2024) | expected risk, for losses monotone in λ | selective error is a ratio and need not be monotone in λ; the bound holds only in expectation |
| Conformal selection with BH (Jin and Candès, 2023) | expected false discovery rate | valid and often accepts more, but "on average over calibration draws" is weaker than spec 5.2; kept as the optional comparison (spec 5.5) |
| Clopper–Pearson bound at every grid λ, take the lowest ≤ α | each λ on its own | choosing among 201 bounds after seeing them needs a Bonferroni correction (δ/201): at α = 0.05 with zero errors that needs 149 accepted items instead of 45 |
| **Fixed-sequence binomial testing (Learn-then-Test; Angelopoulos et al., 2025)** | r(λ̂) ≤ α with probability ≥ 1 − δ | **chosen** |

## Decision

Implement spec 5.3 exactly. Test H₀: r(λ) > α at each point of a grid fixed in `Settings`
before any data is seen (0 to 1, step 0.005, 201 points), strictest first, with
p_λ = BinomCDF(e_λ; n_λ, α). Skip λ with n_λ < m_min (10), stop at the first p_λ > δ, and
take λ̂ as the last certified λ; if none is certified, the unit is NOT_CERTIFIABLE. Calibrate
each field separately and pool by field group only as a labelled fallback (spec 5.4). Report
the Clopper–Pearson upper bound at λ̂ for display only.

**Why it is valid.** For a fixed λ and given n_λ, the accepted calibration items are an
i.i.d. sample of items with s ≥ λ, so e_λ ~ Binomial(n_λ, r(λ)) and p_λ is a valid p-value.
Because the order is fixed in advance, certifying any λ with r(λ) > α requires first rejecting
the earliest such λ in the order, which happens with probability at most δ. No multiplicity
correction is needed.

## Consequences

- The promise matches spec 5.2 and needs no model of the score. The computation is one sort,
  cumulative sums and `scipy.stats.binom.cdf`. Required sample sizes are computed in code
  (`calibrate.required_n`); the numbers in this ADR reproduce the spec 5.4a table exactly.
- Power drops when errors are not monotone in the score: one bad grid point near the top stops
  the sequence early. Validity is unaffected.
- The bound holds **per calibration unit**. With F independent fields at δ = 0.1, the chance
  that at least one field's bound fails can reach 1 − 0.9^F (0.57 for F = 8), and F·δ in
  general. **Decided: keep the bound per field** and say "per field" in every message
  (docs/limitations.md). A simultaneous bound (δ/F per field) would need 42 instead of 22
  accepted items per field at α = 0.10 with zero errors, more than the roughly 40-paper
  calibration split of the owner-annotated set can supply, so no field would ever certify.
- Validity needs calibration and new papers to be exchangeable (spec 3), and items within a
  unit to be independent, hence at most one item per paper per field.
- The Clopper–Pearson bound is computed at a λ̂ chosen from the same data. It is shown as a
  description, never as a second guarantee.

## Revisit if

- The P1 guarantee simulation (spec 9.2) shows a violation rate above δ + 0.02.
- **Open point, resolved by ADR 0004.** Skipping sparse thresholds makes the starting point of
  the sequence depend on the scores. `docs/method.md` proves validity when P(wrong | s) does not
  increase with s. The simulation, which includes two non-monotone populations, found no
  violation rate above 0.086. ADR 0004 also replaces the spec's skip rule, which left the
  procedure unable to certify at α ≤ 0.2.
- Most fields come out NOT_CERTIFIABLE at the owner's α for lack of data: compare conformal
  selection (spec 5.5).
