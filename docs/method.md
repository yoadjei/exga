# Method

This page states what exga promises, under which assumptions, and why the promise holds. It is
the reference that every guarantee shown in the app links to.

## What is promised

For one field, exga accepts an extracted value when its confidence score s is at least a
threshold λ̂. With probability at least 1 − δ over the draw of the calibration records, the
error rate among accepted values of that field, r(λ̂) = P(wrong | s ≥ λ̂), is at most α.
Defaults: α = 0.05, δ = 0.1. The statement is **per field**. Each field's bound can fail with
probability up to δ on its own (see `docs/limitations.md`).

It holds when:

1. **exchangeability**: the calibration papers and the new papers come from the same
   distribution;
2. **independence**: each paper contributes at most one calibration item per field;
3. **random audits**: calibration records are a random sample of extracted values, not values
   someone chose to check (spec 5.6);
4. **monotone errors** (for the starting floor only; see below): higher scores are not more
   often wrong.

When a field has too few records of its own, its whole field group's records are pooled.
Assumption 2 then fails across fields, and results are labelled "pooled" (ADR 0005).

## The procedure

Fix, before seeing any data, a grid of thresholds 1.000, 0.995, …, 0.000. For each threshold λ
let n_λ be the number of calibration items with s ≥ λ and e_λ the number of those that are
wrong. Let n₀ = max(m_min, required_n(α, δ, 0)), the fewest accepted items that could certify α
even with zero errors (45 at α = 0.05, δ = 0.1).

Walk the grid from the strictest threshold down:

- if n_λ < n₀, skip λ: no labelling of so few items could pass;
- otherwise compute p_λ = BinomCDF(e_λ; n_λ, α), the probability of seeing e_λ or fewer errors
  if the true error rate were α;
- if p_λ ≤ δ, certify λ and continue; otherwise stop.

λ̂ is the last certified threshold. If none is certified, the field is NOT_CERTIFIABLE and
every value is flagged for checking. This is fixed-sequence testing in the Learn-then-Test
framework (Angelopoulos et al., 2025), with the starting floor of ADR 0004.

## Why it holds

**One threshold.** Fix λ and condition on n_λ = n. The n accepted calibration items are an
i.i.d. sample from the items with s ≥ λ, so e_λ ~ Binomial(n, r(λ)). If r(λ) > α, then
P(p_λ ≤ δ) ≤ δ, because the binomial CDF falls as the error rate rises. So p_λ is a valid
p-value for H₀: r(λ) > α.

**The sequence.** Call λ a *null* when r(λ) > α. A wrong guarantee means certifying a null.
Since the walk stops at the first failure, certifying any null requires certifying the first
null that is tested. Without skipping, the first tested null is fixed in advance and is
certified with probability at most δ. No correction for testing 201 thresholds is needed.

**The starting floor.** With skipping, which null is tested first depends on the scores. Let
λⱼ be a null and λᵢ the null just before it in the grid. λⱼ is the first null tested exactly
when n(λᵢ) < n₀ ≤ n(λⱼ). The probability of a wrong guarantee is at most the sum, over nulls
λⱼ, of P(λⱼ is certified and is the first null tested). These events are disjoint, so the sum
is at most δ provided

    P(certify λⱼ | n(λᵢ) < n₀ ≤ n(λⱼ)) ≤ δ  for every null λⱼ.

Condition further on n(λⱼ) = n and n(λᵢ) = a. The accepted items are a items with s ≥ λᵢ
(error rate r_high) and n − a items with λⱼ ≤ s < λᵢ (error rate r_band). If P(wrong | s) does
not increase with s, then r_high ≤ r_band. Fewer high items then means stochastically more
errors and a lower chance of passing. So conditioning on a < n₀ can only lower the probability
of certification below its unconditional value, which is at most δ. The bound holds.

Without the monotone assumption the argument does not go through. A small inflation is then
possible in principle. The guarantee simulation therefore also checks two populations built to
break the assumption: errors concentrated in a band of middling scores, and a few
overconfident errors at the very top.

## Evidence

`make verify-guarantee` draws 1,000 calibration sets for each of 30 configurations:
5 populations × α ∈ {0.05, 0.10, 0.20} × n ∈ {200, 1,000}. It checks how often the certified
threshold's true error, computed exactly or by numerical integration, exceeds α. The largest
violation rate is 0.086, against δ = 0.1 and the spec's allowance δ + 0.02. The full table is in
`results/guarantee_simulation.csv`. With biased calibration (half of the wrong values
dropped), the violation rate is 0.84; the test suite checks this to show why only random
audits may enter calibration.

## What is reported alongside the threshold

- the number of calibration records and the raw error rate among them;
- the number of accepted calibration records at λ̂ and their errors;
- the one-sided (1 − δ) Clopper–Pearson upper bound on the error at λ̂. Certification at λ̂ is
  equivalent to this bound being at most α. Because λ̂ was chosen from the same data, the bound
  describes the calibration set; it is not a second guarantee.

## Minimum calibration sizes

Accepted calibration items needed to certify α at δ = 0.1, computed by `calibrate.required_n`:

| α | 0 errors | 1 error | 2 errors |
|---|---|---|---|
| 0.05 | 45 | 77 | 105 |
| 0.10 | 22 | 38 | 52 |
| 0.20 | 11 | 18 | 25 |
