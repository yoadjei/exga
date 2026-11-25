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
