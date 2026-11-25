# Limitations

Recorded as they are found. Each entry says where it comes from and how exga is meant to
handle it. Nothing below is implemented yet unless it says so.

## The statistical guarantee

- **Exchangeability.** The error bound holds only if calibration papers and new papers come
  from the same distribution (spec 3 and 5.2). A batch of papers from another discipline,
  journal or decade can break it, and exga cannot detect that. Planned mitigation (spec 5.6):
  show per-field audit counts and ask for random audits on each new batch, so the calibration
  set keeps pace with the papers being processed.
- **Per field, not all fields at once.** Each field's bound can fail with probability up to δ
  on its own. With F independent fields at δ = 0.1, the chance that at least one field's bound
  fails can reach 1 − 0.9^F (0.57 for F = 8). Claims shown to users must therefore say "per
  field". A simultaneous bound over 8 fields would roughly double the calibration data each
  field needs (zero-error case at α = 0.10: 42 accepted items instead of 22). See ADR 0001;
  the choice is open for the owner (`docs/PROGRESS.md`).
- **Independence within a field.** The binomial test assumes calibration items are
  independent. That holds when each paper contributes at most one item per field. Pooling
  several fields from the same paper breaks it (one badly parsed PDF causes several errors at
  once), so pooled results must be labelled as assuming independence (spec 5.4).

## Correctness rules (labels)

- Numeric matching reads the first number in a value. It does not understand ranges
  ("18–65"), inequalities ("< 0.001"), European decimal commas ("1,5" reads as 1) or unit
  conversions (45% and 0.45 do not match). Fields should ask for one number in a stated unit.
- Text matching is lexical. Paraphrases with little word overlap count as wrong unless listed
  as synonyms (short_text and categorical) or above the token-F1 threshold. Agreement with the
  owner's judgements is to be measured on 50 items (spec 13). See ADR 0003.
