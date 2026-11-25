# Progress

## Current state

- **Phase:** P0 (setup). Everything in P0 is built and passes locally. The acceptance check has
  two parts still outside my control: a CI run on GitHub, and owner review of ADRs 0001–0002.
  P1 (matching and calibration core) comes next.
- **Branch:** `chore/p0-setup`, 7 commits on top of `main`, not merged. A local hook blocks
  edits on `main`, so work happens on branches; merge after CI is green (spec 0A.8).
- **Last updated:** 2026-11-25

## P0 acceptance check (spec section 12)

| Criterion | Status | Evidence |
|---|---|---|
| CI green | local equivalent passes; GitHub run pending | A fresh clone with `UV_LOCKED=1` runs `uv sync --locked`, `ruff check`, `ruff format --check`, `mypy` (strict, 11 files) and `pytest` (78 passed, 100% line and branch coverage) on Python 3.11.16, all passing; `uv build` produces sdist and wheel. The repo has no GitHub remote, so `.github/workflows/ci.yml` has never run. `make` is not installed here, so its recipes were run as their underlying commands. |
| ADRs reviewed by owner | pending | [ADR 0001](adr/0001-risk-control-method.md), [ADR 0002](adr/0002-dependencies.md) |

## Done (session 2026-11-25)

- Repository initialised; owner's `CLAUDE.md` and spec committed as given, then the project
  was renamed from extractguard to exga in a separate commit (20 lines).
- Tooling: `pyproject.toml` (hatchling, ruff, mypy strict with the pydantic plugin, pytest,
  coverage), `uv.lock`, `.python-version` (3.11), `Makefile`, CI workflow, `.gitignore`,
  `.gitattributes` (LF everywhere), MIT `LICENSE`, minimal `README.md`.
- `exga/errors.py`: `ExgaError` and `ConfigError`, `PdfParseError`, `LLMResponseError`,
  `InsufficientCalibrationError`.
- `exga/settings.py`: `Settings` with the calibration group (α 0.05, δ 0.1, m_min 10, grid
  step 0.005) and `load_settings`, which raises `ConfigError` naming the bad setting.
- `exga/schemas.py`: `FieldSpec`, `Paper`, `SampleAnswer`, `SpanLocation`, `Signals`,
  `Extraction`, `CalibrationRecord`, `ThresholdResult`, `TokenLogprob`, `RawResponse`.
- `exga/llm/base.py` (`LLMClient` protocol) and `exga/llm/mock.py` (`MockLLMClient`).
- ADR 0001 and ADR 0002; `docs/limitations.md`.

## Test status

78 tests pass; 100% line and branch coverage of `exga/`; ruff, format check and mypy strict
are clean. Coverage is reported but not yet gated (see next step).

## Decisions

- **ADR 0001**: fixed-sequence binomial testing for threshold certification (spec 5.3 as written).
- **ADR 0002**: httpx behind `LLMClient`, no orchestration frameworks; each dependency enters
  with the code that first imports it; pyyaml added to the spec's list.
- Smaller choices, explained in commit messages, with no ADR needed:
  - flat `exga/` layout, as in spec section 8;
  - settings groups arrive with their first consumer, so P0 has only `calibration`;
  - schema refinements in line with spec 0A.1: typed `location` and `signals` instead of
    dicts, and `ThresholdResult` carrying α, δ, `n_cal` and `errors_cal` so messages can be
    worded from the result alone;
  - `_Record`, a config-only base model, so mypy rejects mutation of records statically;
  - `LLMClient` is a `Protocol` and takes `seed` (it is part of the spec 7.2 cache key);
  - the mock client lives in the library, so it is type-checked against `LLMClient`;
  - Makefile rather than justfile; CI on ubuntu with Python 3.11 only;
  - ruff format skips Markdown, so it never rewrites the spec's code snippets;
  - `tasks/` (personal session notes) is git-ignored.

## Open questions for the owner

1. **Review ADR 0001 and ADR 0002.** This is part of P0's acceptance check. Recommendation:
   accept both. The two points below need your judgement.
2. **PyMuPDF is AGPL-3.0** (ADR 0002). exga's own code can stay MIT, but anyone distributing
   exga with PyMuPDF, or running a modified copy as a network service, must meet the AGPL
   terms. Recommendation: keep PyMuPDF (the spec names it, and it gives word boxes and page
   rendering in one package) and state the dependency's licence in the README from P2. The
   alternative is pdfplumber (MIT), which I would benchmark in P2 before switching.
3. **Per-field or simultaneous guarantee** (ADR 0001, `docs/limitations.md`). As specified,
   each field's bound holds with probability 1 − δ on its own; with 8 fields at δ = 0.1, the
   chance that some field's bound fails can reach 0.57. Recommendation: keep it per field and
   say "per field" in every message. A simultaneous bound (δ/F per field) would roughly double
   the calibration data each field needs (42 instead of 22 accepted items at α = 0.10). This
   changes what the tool promises, so it is your decision.
4. **`.env.example` was not created.** Your permission settings deny writing it (it matches a
   `.env*` rule). Either create it yourself with the content below, or allow that one file.
   ```
   # copy to .env for local overrides; .env is git-ignored and must never be committed.
   # every setting can be set with an EXGA_ variable; nested groups use a double underscore.
   # environment variables take precedence over values in this file.
   EXGA_CALIBRATION__ALPHA=0.05
   EXGA_CALIBRATION__DELTA=0.1
   ```
5. **GitHub remote.** CI cannot run until the repository is pushed. Create the GitHub repo, push
   `main` and `chore/p0-setup`, and open a pull request; merge once CI is green. I have not
   pushed anything.

Heads-up, no action needed yet: ADR 0001 has an open point about the m_min skip rule. P1 will
test it; if the procedure needs to change, I will bring it to you before changing it.

## Known issues (environment)

- `uv` 0.12.19 was installed with pip into
  `C:\Users\adjei\AppData\Local\Python\pythoncore-3.14-64\Scripts`, which is not on `PATH`.
  Add that folder to `PATH` so `uv` and `make` work in new shells.
- GNU make is not installed: `winget install ezwinports.make`. Until then, run the commands in
  the `Makefile` directly.

## Next step

Start P1 (re-read spec 5, 6.4 and 9.2 first):
1. `matching.py`, test first: the spec 6.4 rules (number parsing for "1,234", "1.2k",
   "n = 120" and number words; categorical synonyms; token-F1 thresholds as settings).
2. `calibrate.py`: fixed grid built from `grid_step`, `fit_threshold`, `required_n`,
   Clopper–Pearson bound; hypothesis property tests (spec 0A.4).
3. `tests/test_guarantee_sim.py` (spec 9.2), plus non-monotone error curves for the ADR 0001
   open point; `make verify-guarantee` and `scripts/bench.py`.
4. Add numpy, scipy (with `scipy-stubs` for mypy) and hypothesis, plus a 90% coverage floor
   on the pure-core modules once they exist.
