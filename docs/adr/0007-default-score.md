# ADR 0007: details of the default score

- **Status:** accepted 2026-11-25 (the owner delegated this decision)
- **Date:** 2026-11-25
- **Spec:** section 7.4; code: `exga/score.py`, `matching.contains_value`

## Context

Spec 7.4 defines three signals and a weighted-average score, but leaves four questions open.
Each changes which values are accepted, so each is fixed here before any data is seen.

## Decisions

1. **"Not reported" answers have no source signal.** The source check asks whether a quote
   supports a value. A "not reported" answer has no value and no quote, so scoring it 0 would
   punish every correct "not reported" answer. The signal is unavailable instead, and the
   score is the weighted average of agreement and logprob.
2. **The source check reads the paper, not the model's quote.** The quote is located by exact,
   normalised or fuzzy match (similarity ≥ 0.9). Fuzzy matching tolerates small differences,
   and "A total of 120 participants" matches "A total of 129 participants" at about 0.96. So
   the value is checked against the text found in the paper. Otherwise a misquoted number
   would earn the full signal.
3. **"States the value" follows the field's correctness rule.**
   - A numeric value must appear as a number within the field's tolerance.
   - A categorical value, or one of its synonyms, must appear as a phrase.
   - A short_text value must appear as a phrase.
   - For long_text, at least 60% (`long_text_min_f1`) of the value's words must appear,
     because a long answer paraphrases its source.
4. **An item without a usable greedy answer scores 0.** Its value is unknown, not "not
   reported", and the record says so (`Extraction.failed`). The decision rule stays exactly
   `score ≥ λ̂`, the same in calibration and in use, so the guarantee covers these items too.
   Only a threshold of 0 accepts them, and then calibration counted them the same way.

Default weights are equal (1, 1, 1). This is the only choice that needs no data, and the
logistic score in spec 7.4 is the data-driven alternative to compare against.

## Consequences

- Fields that are often unreported are scored on two signals for those items, so their scores
  are not directly comparable with those of items that have a value. Calibration is per field
  and uses the same rule, so the guarantee is unaffected.
- A numeric value written only in words inside the quote counts only when the words form the
  first number phrase in the quote (`numbers_in`). This is a known gap and costs at most
  half a signal.
