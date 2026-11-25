# Limitations

What exga cannot do, or promises only under conditions. Each entry says where it comes from and
how exga handles it. Findings from building exga are also listed in
[PROGRESS.md](PROGRESS.md#findings-the-owner-should-know-about).

## The statistical guarantee

- **Exchangeability.** The error bound holds only if calibration papers and new papers come
  from the same distribution (spec 3 and 5.2). A batch of papers from another discipline,
  journal or decade can break it, and exga cannot detect that. The Calibrate page shows how
  many checked values each field's threshold rests on, and random audits of each new batch
  keep the calibration set in step with the papers being processed (spec 5.6).
- **Per field, not all fields at once.** Each field's bound can fail with probability up to δ
  on its own. With F independent fields at δ = 0.1, the chance that at least one field's bound
  fails can reach 1 − 0.9^F (0.57 for F = 8). Claims shown to users therefore say "per
  field". A simultaneous bound over 8 fields would roughly double the calibration data each
  field needs (zero-error case at α = 0.10: 42 accepted items instead of 22). ADR 0001 keeps
  the bound per field, and every guarantee message says "for this field" (`exga/messages.py`).
- **Certifiability depends on the field.** A field is certified only when enough checked
  values clear the threshold with few enough errors: at α = 0.05 and δ = 0.1, at least 45
  accepted values with no error, 77 with one ([method.md](method.md#minimum-calibration-sizes)).
  A field the model often gets wrong may never be certified at a small α; it is then shown
  as Not certifiable with its raw error rate, and every value is checked by hand. On the
  benchmark of ADR 0008, about 35 calibration items per field remain after exclusions, so
  α = 0.20 is the realistic level for per-field claims there.
- **Independence within a field.** The binomial test assumes calibration items are
  independent. That holds when each paper contributes at most one item per field. Pooling
  several fields from the same paper breaks it (one badly parsed PDF causes several errors at
  once), so pooled results are labelled as assuming independence (spec 5.4, ADR 0005).
- **The starting floor assumes monotone errors.** Skipping thresholds with too few accepted
  items is proven valid when higher scores are not more often wrong; otherwise a small
  inflation is possible in principle. The guarantee simulation includes two populations
  built to break the assumption; across all 30 configurations the largest violation rate is
  0.086 against δ = 0.1 (`results/guarantee_simulation.csv`, [method.md](method.md),
  ADR 0004).
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
  drawn by exga's random audit enter calibration from the Review and Audit pages (ADR 0009).
  The database cannot detect a person who labels carelessly.
- **Imported records are trusted.** A `gold.csv` or an experiment's records file enters
  calibration as given. exga cannot check that gold values were labelled without seeing the
  model's answers, or that an experiment's papers, model and prompt match the project's.

## Papers

- **Text PDFs in English.** exga reads the PDF's text layer. A PDF with fewer than 200
  extractable characters is treated as scanned and refused; there is no OCR. Prompts,
  matching rules and the benchmark are English; other languages are untested.
- **Values in figures and image tables are not read.** Only text is sent to the model. The
  benchmark items whose data are only in graphics are excluded from the experiments
  (ADR 0008), so results do not cover them.
- **Words hyphenated at a line end** are not always joined by PyMuPDF. Quotes containing them
  are still found by fuzzy search, but score 0.9–1.0 instead of an exact match.

## Correctness rules (labels)

- Numeric matching reads the first number in a value. It does not understand ranges
  ("18–65"), inequalities ("< 0.001"), European decimal commas ("1,5" reads as 1) or unit
  conversions (45% and 0.45 do not match). Fields should ask for one number in a stated unit.
- Text matching is lexical. Paraphrases with little word overlap count as wrong unless listed
  as synonyms (short_text and categorical) or above the token-F1 threshold. Agreement with a
  person's judgements has not yet been measured (spec 13). See ADR 0003.

## Models and use

- **The model must return token log-probabilities** for all three signals (ADR 0006).
  Without them (`EXGA_HOSTED__LOGPROBS=false`) the score uses agreement and the evidence
  check only.
- **Paper text leaves the computer** when the endpoint is a hosted service. The app names
  the service and asks for consent first; a local server keeps everything on the machine.
- **The Review page records corrections, not confirmations.** A value someone checked and
  found right leaves no trace in the export (ADR 0012).
- **One person, one computer.** The app serves this computer only, and a project folder is
  not meant to be opened by two people at once.
