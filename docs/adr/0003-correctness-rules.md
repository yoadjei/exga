# ADR 0003: correctness rules per field type

- **Status:** accepted
- **Date:** 2026-11-25
- **Spec:** section 6.4; code: `exga/matching.py`

## Context

Every calibration label (`wrong`) comes from one function, `is_correct(pred, gold, spec)`. If
it is too strict, correct values count as errors, fewer thresholds certify and the tool looks
worse than it is. If it is too lax, wrong values count as correct and the certified error
bound is false. Spec 6.4 fixes the rule for each field group. These are the details it leaves
open, and how they were settled.

## Decisions

| Question | Options considered | Decision and reason |
|---|---|---|
| Which number in "120 participants (60 per arm)"? | first number; largest; reject text containing several numbers | **First number.** Answers are asked for as a single value (spec 6.3), and the model usually leads with it; rejecting such text would label many correct values wrong. |
| Is "m" a million suffix? | yes; no | **No.** In papers "12 m" means metres or months far more often than millions. "k", "thousand", "million" and "billion" are read. |
| Is "-" a minus sign in "COVID-19"? | always; only when not after a letter or digit | **Only when not after a word character**, so "COVID-19" is 19, not −19. The unicode minus and en dash are also read as minus. |
| Exact numeric arithmetic | float; decimal | **Decimal while parsing.** Float would turn "1.1k" into 1100.0000000000002 and fail an exact (zero-tolerance) match. |
| Punctuation in text | remove all; replace all with spaces | **Dashes, underscores and slashes become spaces; other punctuation is removed.** "case-control" and "case_control" then match "case control", and "U.S.A." matches "USA". |
| Synonyms | categorical only (spec); also short_text | **Also short_text.** Without it, "USA" and "United States" have token F1 = 0, so a correct country is labelled wrong. Synonyms are explicit, per field, and stored in `fields.yaml`, so they can be read and audited. With none defined, the behaviour is exactly the spec's. |
| Malformed gold labels | silently count as mismatch; raise | **Raise `ConfigError`** for a numeric gold that is not a number or a categorical gold outside `allowed_values`. A silent mismatch would turn a labelling mistake into a model error. |
| Comparing two model samples (agreement signal) | reuse `is_correct`; separate function | **`values_match`**, the same rule without gold checks, which never raises on what a model wrote. |

## Consequences

- One module decides every label, with a unit test for each case in the table.
- The F1 thresholds (0.8 short text, 0.6 long text) are settings, not constants.
- Known blind spots, to be measured against 50 owner judgements as spec 13 requires: ranges
  ("18–65"), inequalities ("< 0.001"), European decimal commas ("1,5"), and units that differ
  between prediction and gold (45% vs 0.45). They are listed in `docs/limitations.md`.

## Revisit if

- Agreement with the owner's judgements falls below about 95% on any field group.
- A field needs a rule the table cannot express. Add a field-level option then, not a global
  change.
