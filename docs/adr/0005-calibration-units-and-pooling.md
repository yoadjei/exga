# ADR 0005: calibrate each field on its own, pool by field group only when it must

- **Status:** accepted
- **Date:** 2026-11-25
- **Spec:** section 5.4; code: `calibrate.calibrate_fields`

## Context

The binomial test assumes calibration items are independent. Items from one paper are not
(one badly parsed PDF causes several errors at once), so the spec calibrates each field
separately, where each paper contributes at most one item. Some fields will have too few
records to certify on their own. The spec allows pooling by field group as a labelled fallback
but leaves open when to pool.

## Options

| When to pool | Problem | Verdict |
|---|---|---|
| When the per-field result is NOT_CERTIFIABLE | tries two procedures and keeps the one that certifies: the error probability can reach 2δ | rejected |
| Never | fields with few records are never certified | rejected: wastes the fallback the spec asks for |
| Always | mixes fields with different error rates and breaks independence for all of them | rejected |
| **When the field has fewer records than `start_floor`** | the choice depends on counts only, never on labels | **chosen** |

## Decision

A field with at least `start_floor(α, δ, m_min)` records, the smallest number that could ever
certify, is calibrated on its own records. A field with fewer is given the result of its whole
field group (`numeric`, `categorical`, `short_text`, `long_text`), marked `pooled=True` and
named after the group. If no other field in the group has records, pooling adds nothing and
the field keeps its own, uncertified, result. Records of fields no longer in the field list
are ignored, and a record whose group disagrees with its field's current spec raises
`ConfigError`.

## Consequences

- Because the decision to pool never looks at labels, there is one test per field and no
  selection between procedures.
- A pooled guarantee is about the mix of fields in the group, not about the short field
  itself, and it assumes errors are independent across fields. Every message about a pooled
  result says so (spec 5.4, `messages.py`).
- Pooled results are computed once per group and shared by every short field in it.

## Revisit if

- The clustering check (spec 5.4) shows per-paper error counts far more variable than binomial;
  then pooling should be removed and short fields left uncertified.
