# ADR 0009: only random audits update calibration

- **Status:** accepted 2026-11-25 (the owner delegated this decision)
- **Date:** 2026-11-25
- **Spec:** sections 5.6, 7.7, 9.2; code: `exga/audit.py`, `exga/store.py`, `exga/simulation.py`

## Context

Users check values while they work: they open flagged values, fix wrong ones, and sometimes
confirm accepted ones. Every check is a label, so it is tempting to add every check to the
calibration records. The binomial test, however, needs calibration records that are
exchangeable with the items the threshold is applied to. A label enters as a calibration
record only if it was chosen independently of whether the value is right.

## Options

| Source of new records | Exchangeable? | Verdict |
|---|---|---|
| every check a user makes | no: which values get checked, and which checks get logged, depends on what the user sees, including errors | rejected |
| checks of flagged values only | no: these records describe low scores, and corrections are mostly errors | rejected |
| **a uniform random sample of all items, accepted and flagged, drawn by exga** | yes, if every drawn item is labelled | **chosen** |

## Decision

- Each review session, exga draws a uniform random sample from all extracted items: a share of
  `audit.rate` (default 5%), at least `audit.min_items` (3). Items already audited are not drawn
  again, so no item gives two records. Each drawn item is labelled with the value found in the
  paper. Only an item that cannot be checked at all, for example because its file is missing,
  may be skipped. Skips are counted and shown, because skipping the hard items, which are more
  often wrong, would bias the records. A batch closes only when every item is labelled or
  skipped.
- Only labels of drawn items become `CalibrationRecord(source="random_audit")`. Corrections a
  user makes elsewhere are stored as data corrections and never enter calibration.
- After each completed batch, thresholds are recomputed and the result is appended to a
  versioned threshold log. Records are never edited or deleted.

## Consequences

- The simulation (`simulate_audit_policies`) shows the difference. Under random audits the
  per-version violation rate stays at δ or below. When wrong values are logged less often than
  right ones, it rises well above δ.
- **Repeated recalibration is repeated testing.** Each threshold version holds its guarantee
  with probability at least 1 − δ at the time it is computed. The probability that some version
  in a long log was violated at some point can exceed δ. The simulation reports both rates. The
  user-facing claim is about the current threshold only, and `docs/limitations.md` says so.
- Users label items they did not choose. The Audit screen must make this feel worthwhile by
  showing how the guarantee changes as records accumulate.
