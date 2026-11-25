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
  field needs (zero-error case at α = 0.10: 42 accepted items instead of 22). ADR 0001 keeps
  the bound per field, and every guarantee message says "for this field" (`exga/messages.py`).
- **Independence within a field.** The binomial test assumes calibration items are
  independent. That holds when each paper contributes at most one item per field. Pooling
  several fields from the same paper breaks it (one badly parsed PDF causes several errors at
  once), so pooled results must be labelled as assuming independence (spec 5.4).
- **A threshold log is repeated testing.** Every completed audit batch recomputes the
  thresholds (spec 5.6). Each version, at the time it is computed, is violated with
  probability at most δ. Over a log of many versions, the chance that some version was
  violated at some point is higher. In `results/audit_simulation.csv` (10 versions, δ = 0.1),
  random audits keep each version's violation rate at 0.000–0.034, but 10–13% of logs contain
  a violated version. exga's claims are therefore about the current threshold only. A bound
  that holds over the whole log at once would need an anytime-valid method, such as a
  confidence sequence. That is out of scope (ADR 0009).
- **Records must not depend on labels.** If wrong values are logged half as often as right
  ones, the share of violated versions rises to 0.21–0.46 in the same simulation. Only items
  drawn by `exga`'s random audit enter calibration (ADR 0009). The database cannot detect a
  person who labels carelessly.

## Correctness rules (labels)

- Numeric matching reads the first number in a value. It does not understand ranges
  ("18–65"), inequalities ("< 0.001"), European decimal commas ("1,5" reads as 1) or unit
  conversions (45% and 0.45 do not match). Fields should ask for one number in a stated unit.
- Text matching is lexical. Paraphrases with little word overlap count as wrong unless listed
  as synonyms (short_text and categorical) or above the token-F1 threshold. Agreement with the
  owner's judgements is to be measured on 50 items (spec 13). See ADR 0003.
