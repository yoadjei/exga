# Progress

## Current state

- **Last updated:** 2026-11-25
- **Phase:** P0–P8 built. P3's real-PDF check, P5's annotated set, P7's walk-through and P8's
  real run wait for the owner (see "Owner actions"). P9 (user study) next.
- **Repository:** https://github.com/yoadjei/exga. Each phase is built on a branch, pushed, and
  fast-forwarded into `main` once GitHub CI is green. A local hook blocks edits on `main`.
- **Decision authority:** on 2026-11-25 the owner delegated all remaining decisions to the lead
  engineer, after reasoning. Each is recorded in an ADR or in the decisions below.

## Phases (spec section 12)

| Phase | Acceptance check | Status | Evidence |
|---|---|---|---|
| P0 Setup | CI green; ADRs reviewed | **done** | CI run on `chore/p0-setup` green; ADRs 0001–0002 accepted under delegation |
| P1 Matching and calibration core | 9.2 test passes; edge cases covered | **done** | `tests/test_guarantee_sim.py`; `make verify-guarantee`: 30/30 configurations within δ + 0.02 (`results/guarantee_simulation.csv`) |
| P2 PDF processing | fixture tests pass; highlights render | **done** | `tests/test_pdf.py`, `tests/test_document.py`; a highlighted fixture page was rendered and inspected; `make bench`: 20-page PDF loads in 85 ms |
| P3 Extraction | 10 real PDFs, < 5% parse failures | **built; check waits for a model endpoint** | code and offline tests done (`tests/test_extract*.py`, `tests/test_cli.py`); `exga extract` reports the parse-failure rate in `run.json` |
| P4 Scoring and decisions | end-to-end test with mock client | **done** | `tests/test_end_to_end.py` (spec 9.3); `make bench`: scoring, calibration and decision of 10,000 items in 168 ms |
| P5 Data | gold files validated; splits reproducible | **done for the benchmark; annotated set waits for labels** | benchmark gold validated on all 550 TEST items; split shuffle pinned by a golden test; `exga check-gold` validates the owner's file |
| P6 Audit and updating | unit tests; biased vs random audit simulation | **done** | `tests/test_audit*.py`, `tests/test_store.py`, `tests/test_project.py`; `results/audit_simulation.csv`: random audits 0.000–0.034 of versions violated, biased logging up to 0.456 |
| P7 Web app | owner completes upload → review → audit → export | **built; walk-through waits for the owner and a model endpoint** | `tests/test_app.py` drives every page with AppTest (24 tests, upload through export); a real-browser pass on a running server checked rendering, the highlighted PDF page and the privacy settings |
| P8 Experiments | tables and figures from configs | **built; the real run waits for model endpoints** | `tests/test_experiments_run.py` runs `experiments/run.py` end to end on a mock model and a benchmark in the downloaded layout: all four tables, three figures (rendered and inspected), the records file and the manifest; `tests/test_evaluate.py`, `tests/test_experiment.py` (including the annotated set as a second dataset). No results exist yet, and none are made up |
| P9 User study | data collected and summarised | | |
| P10 Packaging and docs | clean `pip install`; app runs from README | | |
| P11 Thesis support | owner sign-off | | |

## Test status

637 tests pass in about 60 s. The pure core (`matching`, `calibrate`, `simulation`, `document`,
`score`, `decide`, `labels`, `messages`, `splits`, `audit`, `views`, `evaluate`) has 97–100%
line and branch coverage, gated at 90% in `make test`; the whole package, app pages included,
is at 96%. ruff and mypy (strict, now also over `experiments/`) are clean. `make bench`: scoring, calibration and decision of 10,000 items take 168 ms, and a
20-page PDF loads in about 66 ms (budget 1 s each). Source matching takes 0.6 ms per item for
an exact quote and about 33 ms when it falls back to fuzzy search.

## Decisions

| ADR | Decision |
|---|---|
| [0001](adr/0001-risk-control-method.md) | fixed-sequence binomial testing; the bound is per field |
| [0002](adr/0002-dependencies.md) | httpx behind `LLMClient`, no frameworks; dependencies enter with first use; keep PyMuPDF (AGPL), pinned to 1.x because 2.x adds about 60 MB of unused dependencies |
| [0003](adr/0003-correctness-rules.md) | correctness rules: first number, no "m" suffix, decimal parsing, synonyms also for short_text, malformed gold raises |
| [0004](adr/0004-sequence-start-floor.md) | start testing at required_n(α, δ, 0): the spec's m_min = 10 rule could never certify at α ≤ 0.2 |
| [0005](adr/0005-calibration-units-and-pooling.md) | per-field calibration; pool by field group only when a field has fewer records than the floor |
| [0006](adr/0006-model-back-ends.md) | one OpenAI-compatible chat-completions client for hosted and local (vLLM, llama.cpp) models; Claude rejected for lack of logprobs and temperature |
| [0007](adr/0007-default-score.md) | default score: no source signal for "not reported", the paper's text (not the quote) decides, failed items score 0 |
| [0008](adr/0008-benchmark-mapping.md) | Yun et al. benchmark: 8 numeric fields, one triplet per (paper, field), graphics-only data excluded, DEV papers kept apart |
| [0009](adr/0009-random-audit-updates.md) | only uniform random audits add calibration records; a threshold log is repeated testing |
| [0010](adr/0010-streamlit-app.md) | a local Streamlit app over `exga.project` and `exga.views`, shipped in `exga/app/`; served on localhost only, without usage statistics or the Deploy button |
| [0011](adr/0011-experiment-design.md) | experiments: 50 paper-level 30/40/30 splits, bootstrap intervals over papers on the primary split, three baselines, the signal ablation as reweighting, results in hashed folders with a manifest |

Smaller choices are explained in commit messages.

## Findings the owner should know about

1. **The spec's threshold procedure, read literally, never certifies** at α ≤ 0.2. With
   m_min = 10, the first tested threshold has about 10 items, but at α = 0.05 even zero errors
   need 45, so the sequence stops at once. ADR 0004 fixes this without weakening the guarantee.
   The fix is proven valid when higher scores are not more often wrong, and checked by
   simulation when they are.
2. **One spec property is false.** "Adding a correct high-score record never removes
   certification" (spec 0A.4) cannot hold for any procedure that skips sparse thresholds. A
   test shows the counterexample. The test suite checks the true version instead: correcting a
   wrong label never removes certification.
3. **Biased calibration breaks the guarantee badly.** Dropping half of the wrong values raises
   the violation rate from about 0.06 to 0.84. This supports the random-audit-only rule (5.6).
4. **PyMuPDF 2.x is much heavier than 1.x.** It installs onnxruntime and seven other packages
   exga does not use. exga stays on 1.28 (ADR 0002 amendment).
5. **Words hyphenated at a line end are not always joined by PyMuPDF.** Quotes containing them
   are still found by the fuzzy step of span search, which is slower and scores 0.9–1.0
   instead of an exact match.

6. **A long threshold log is repeated testing.** Each recalibration is valid on its own, but
   in 10% to 13% of simulated 10-version logs some version was violated (δ = 0.1). Claims are
   therefore about the current threshold only (`docs/limitations.md`, ADR 0009).
7. **Logging errors less often than confirmations breaks the guarantee.** With wrong values
   logged half as often, up to 46% of threshold versions are violated.
8. **The benchmark is small per field.** After the exclusions in ADR 0008 there are 88 TEST
   papers, about 35 calibration items per field (16 for event counts). At α = 0.10 a field
   needs at least 22 accepted items with no errors, so several fields will be pooled or not
   certifiable. α = 0.20 is the realistic setting for per-field claims on this benchmark.
9. **Streamlit's defaults are not private.** Started plainly, it listens on every network
   interface (anyone on the same Wi-Fi could open a project's papers), looks up the machine's
   public address through an outside service, sends usage statistics and offers a Deploy
   button to its cloud. `exga app` turns all of these off; a test pins the flags (ADR 0010).
10. **Choosing α after seeing results weakens the guarantee.** The Calibrate page allows a
    change, warns against it, and keeps every change in the threshold log.
11. **Benchmark records certify a project only if its papers resemble the benchmark's** and
    were extracted with the same model and prompt. Records do not carry the model or prompt,
    so exga cannot check this; the Calibrate page says so, and random audits of the project's
    own papers are the recommended source.
12. **On the benchmark, "test error above α" will look high even when the guarantee holds.**
    A test split has about 26 items per field, so chance alone often puts the observed error
    above α. The tables report that rate under this name, next to the mean realised error;
    the guarantee itself is checked by the P1 simulation, where the true error is known
    (ADR 0011).

## Owner actions

1. **P3 acceptance needs a model endpoint.** Either an API key for an OpenAI-compatible
   provider that returns logprobs, or a local vLLM or llama.cpp server. Set
   `EXGA_HOSTED__BASE_URL`, `EXGA_HOSTED__MODEL` and, if needed, `EXGA_HOSTED__API_KEY`, plus
   the token prices and `EXGA_HOSTED__BUDGET_USD`. Then run
   `exga extract --papers <10 PDFs> --fields examples/fields.yaml --out runs/p3`; the check
   passes if `parse_failure_rate` in `runs/p3/run.json` is below 0.05.
2. **The annotated set (spec 10.2)** follows `data/annotated/README.md`: pick 50–100
   open-access PDFs, run `exga annotation-sheet`, label without looking at model output, have
   20% double-labelled, then run `exga check-gold`.
3. **P7 walk-through.** With a model endpoint configured as in action 1, run `exga app`
   (or `make app`), create a project in an empty folder, add fields, upload a few PDFs, run,
   calibrate (start a random audit), review, finish the audit and export. Note anything that
   needed explanation; the check passes when nothing did.
4. **P8 real run.** Fill in `model:` for each model in `experiments/main.yaml`,
   `experiments/ablations.yaml` and `experiments/annotated.yaml` (the model must return token
   logprobs; the open-weight entry expects a server at `localhost:8000`), set the key and a
   budget as in action 1, then run `make experiments`. The annotated run needs action 2
   first, with the papers in `data/annotated/papers`. Results land in
   `results/<name>-<hash>/` with tables, figures, a records file per model for the Calibrate
   page, and a manifest. Extraction sends paid requests once; reruns use the response cache.

## Known issues (environment)

- `uv` and `make` are not on PATH for new shells. `C:\Users\adjei\Downloads\fix-dev-path-all-users.ps1`
  installs both machine-wide with winget; it must be run once from an administrator PowerShell.
  It has not been run or tested.

## Next step

P9: user-study materials (spec 11.3): consent form, protocol, task sheet, SUS questionnaire
and an analysis script that summarises the collected responses.
