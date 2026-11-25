# Build Specification: Uncertainty-Aware Data Extraction from Research Papers with Guaranteed Error Rates

**Owner:** Yaw Osei Adjei, BSc Computer Science, KNUST
**Purpose of this file:** to give any engineer or AI coding agent enough context to build this project from an empty repository to a finished, evaluated, defended system. Read it fully before writing code. When something here is unclear, ask the owner rather than guessing.

---

## 0. How to use this document (instructions for agents)

1. Work phase by phase (Section 12). Do not start a phase until the previous phase's acceptance checks pass.
2. Keep the statistical core (Section 5) exactly as specified. It is what makes the guarantee true. If you think it should change, stop and explain why to the owner.
3. Write tests alongside code. The guarantee test in Section 9.2 must pass before any result is reported.
4. Never hard-code API keys. Read them from environment variables.
5. Never overstate results in docs, README or thesis text. Report what was measured, with confidence intervals.
6. Fix random seeds and cache every LLM response so experiments are reproducible and cheap to rerun.
7. Keep the library (`exga/`) independent of the web app (`app/`). The app only calls the library.

---

## 0A. Engineering standards (read before writing any code)

This project will be read by examiners, graduate admissions committees and future contributors. It must look like it was built by someone who understood every line, not generated in bulk. Act as a principal engineer: make few, deliberate decisions, write them down, and keep the codebase small enough that one person can hold it in their head.

### 0A.1 Architecture principles
- **Functional core, imperative shell.** `matching.py`, `score.py`, `calibrate.py`, `decide.py` and `evaluate.py` are pure: inputs in, values out, no file, network, database or clock access. All I/O lives in `pdf.py`, `llm/`, `store.py`, `cli.py` and `app/`. This is what makes the statistical core testable and defensible.
- **Typed domain, not dicts.** Data crosses module boundaries only as the Pydantic models in `schemas.py`. No `dict[str, Any]` in public signatures. Frozen models for records that must not change after creation (`CalibrationRecord`, `ThresholdResult`).
- **No global state.** Configuration is a single `Settings` object (pydantic-settings) passed in explicitly. No module-level clients, no singletons.
- **Idempotent, resumable pipeline.** Each step is keyed by content: `paper_id = sha256(pdf bytes)`, cache key = hash of (model, prompt version, inputs, sampling params). Rerunning a step never duplicates work or rows. A crashed run resumes where it stopped.
- **Errors are explicit.** Define a small error hierarchy (`ExgaError` → `PdfParseError`, `LLMResponseError`, `InsufficientCalibrationError`, `ConfigError`). Never `except Exception: pass`. Every caught exception is either handled with a specific recovery or re-raised with context.
- **One place for user-facing claims.** All wording that states or implies a guarantee comes from a single module (`messages.py`) and is generated from the `ThresholdResult`. The UI must never say "guaranteed" when the result is pooled, uncertified, or based on fewer than the configured minimum records.

### 0A.2 Things that make code look "vibe-coded" and are not allowed
- Framework sprawl: no LangChain, LlamaIndex or agent frameworks. Two model adapters do not need a plugin system. Call the APIs directly behind the small `LLMClient` interface.
- God files and `utils.py` grab-bags. If a helper has no clear home, the design is wrong.
- Abstractions with one implementation "for the future". Add an interface when the second implementation arrives.
- Copy-pasted prompts inside code. Prompts are versioned files in `prompts/`, loaded by name, and the version is stored with every extraction.
- Magic numbers. Every threshold and tolerance is a named field in `Settings` with a docstring explaining it.
- Broad retries that hide bugs. Retry only on transient network/rate-limit errors, with capped exponential backoff and jitter; never retry on parse errors without the explicit one-shot repair step.
- `print` debugging and emoji logs. Use `logging` with structured context (`paper_id`, `field`, `model_id`, `run_id`).
- Comments that restate the code, AI-style docstrings ("This function is responsible for…"), and TODO graveyards. Docstrings state contract, units, assumptions and failure modes. Open TODOs become GitHub issues.
- Generic UI: default Streamlit look with emoji headers and walls of widgets. See 0A.6.
- Large, untested, multi-purpose commits.

### 0A.3 Dependencies
Every runtime dependency must earn its place. Record the reason in `docs/adr/0002-dependencies.md`. Target runtime set: `pymupdf`, `pydantic`, `pydantic-settings`, `numpy`, `scipy`, `scikit-learn`, `rapidfuzz`, `pandas`, `openpyxl`, `typer`, `httpx`, `streamlit`. The local model back-end (`transformers`, `torch`) is an optional extra (`pip install exga[local]`) so the core installs in seconds on a laptop. Pin with a lock file (`uv` or `pip-tools`).

### 0A.4 Code quality gates (enforced in CI)
- `ruff` (lint and format) with a project config; no blanket ignores.
- `mypy --strict` on `exga/` core modules; the app may be less strict.
- `pytest` with coverage ≥ 90% on the pure core (`matching`, `score`, `calibrate`, `decide`, `evaluate`, `audit`). Coverage is a floor, not a goal; tests must assert behaviour, not just execute lines.
- **Property-based tests** (`hypothesis`) for the calibration algorithm: the returned threshold is always a point on the fixed grid or `None`; accepted-set error on calibration never exceeds the certified bound; results are invariant to input order; adding a correct high-score record never removes certification.
- **Golden tests** for prompts and parsing: fixed model outputs → fixed parsed results, so prompt edits are visible in review.
- The guarantee simulation test (Section 9.2) runs in CI with a fixed seed and a reduced repetition count; the full 1,000-repetition run is a separate `make verify-guarantee` target.

### 0A.5 Operational concerns a senior engineer would not skip
- **Cost accounting.** Every LLM call logs tokens in and out; each run writes a cost summary. Budgets can be set per run and abort the run cleanly when exceeded.
- **Concurrency.** Hosted API calls run through a bounded thread pool (default 4 workers) with a token-bucket rate limiter. No `asyncio` unless profiling shows it is needed.
- **Privacy.** When the hosted model is selected, the app states plainly that paper text is sent to that provider. The local model path keeps everything on the machine. No telemetry.
- **Reproducibility.** Each run writes a manifest: git commit, settings, model IDs, prompt versions, seeds, dataset hashes. Every figure in the thesis is regenerated from a manifest.
- **Database migrations.** SQLite schema has a `schema_version` table and numbered SQL migration files. No silent schema drift.
- **Performance budget.** Scoring, calibration and decision for 10,000 items must complete in under one second on a laptop; PDF loading under 1 second per typical 20-page paper. Measure, do not guess.

### 0A.6 User interface standards
- Design the three core screens (Review, Audit, Calibrate) on paper first; build only what supports the workflow.
- Status is never shown by colour alone: use colour **plus** a text label and icon ("Accepted", "Check", "Not certifiable") for colour-blind users, with contrast meeting WCAG AA.
- Every screen has empty, loading and error states with a clear next action.
- Numbers are formatted for people (e.g. "Error ≤ 5% (90% confidence) · 412 audited values"), with an info link to `docs/method.md`.
- Destructive actions (deleting a project, discarding audits) require confirmation and are undoable where feasible.
- If Streamlit cannot meet these standards for a screen, document the limitation rather than piling on hacks.

### 0A.7 Decision records
Write short Architecture Decision Records in `docs/adr/` (context, decision, consequences, alternatives considered) for at least:
1. Selective-risk control via fixed-sequence binomial testing instead of plain conformal coverage.
2. Dependency set and the choice not to use LLM orchestration frameworks.
3. Random-audit-only calibration updates.
4. Per-group (Mondrian) calibration and the pooled fallback.
5. Streamlit for the interface and its known limits.
6. Correctness rules per field type.

### 0A.8 Workflow
- Small pull requests (aim for under 400 changed lines), one concern each, with a description of what changed, why, and how it was tested.
- Conventional commit messages (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`).
- `main` is always releasable; CI must pass before merge.
- Review checklist for every PR: Is the core still pure? Are claims to users generated from results? Are new numbers named settings? Are tests behavioural? Is there a simpler design?

### 0A.9 Writing standard (README, docs, thesis support text)
Plain, specific and measured. State what the tool does, what it guarantees and under which assumption, and what it does not do. No marketing language, no superlatives, no unverified claims. Every quantitative claim points to a results file.

---

## 1. The project in plain words

Researchers copy data out of papers into spreadsheets (sample sizes, countries, results). AI can do this quickly but makes silent mistakes, so people re-check everything.

This tool:
1. extracts the requested data from PDF papers with a large language model (LLM);
2. gives every extracted value a confidence score;
3. uses a small set of human-checked values to choose a cut-off so that, **among the values it accepts, the error rate is at most α (for example 5%), with high probability**;
4. shows accepted values in green and flagged values in amber, each linked to its highlighted location in the PDF;
5. learns from new human checks without breaking the guarantee;
6. warns the user when a field is too unreliable for any useful guarantee.

It ships as a **Python library** and a **web app** built on that library.

---

## 2. Background the builder must understand

- LLM-assisted extraction is fast but still wrong about 9% of the time in a large prospective study, saving about 41 minutes per study (Gartlehner et al., 2025). Numeric fields are hardest (Yun et al., 2024; Li, Mathrani and Susnjak, 2026). Evaluations agree that humans must still verify (Konet et al., 2024; Bianchi et al., 2025).
- Confidence scores alone (for example self-consistency, Manakul et al., 2023; per-field trust scores, Goh and Mueller, 2026) do not tell the user how many accepted values are wrong.
- **Selective prediction with risk control** turns any score into a guarantee: pick a threshold λ on the score, accept items with score ≥ λ, and choose λ on held-out verified data so the error rate among accepted items is bounded (Geifman and El-Yaniv, 2017; Bates et al., 2021; Angelopoulos et al., 2025). Shrestha and Kim (2026) applied this to LLM extraction on clinical text.
- **Limit:** if the model's error rate on a field is far above α, no threshold can meet α without rejecting almost everything (Kotte, 2026). The tool must detect and report this.

**Novelty of this project (do not overstate):** applying guarantee-backed acceptance to research-paper extraction, combining several confidence signals, safe updating from random audits, and delivering it as a usable open-source tool with an evaluation.

---

## 3. Scope

### In scope
- Text-based PDFs in English; user-defined fields.
- Web app: upload PDFs, define fields, review the green/amber table, click a value to see it highlighted in the PDF, correct values, run random audits, export CSV/XLSX.
- Python library and CLI.
- Confidence signals: sample agreement, token log-probabilities (when available), source matching.
- Risk-controlled threshold per field group, with a "not certifiable" warning.
- Threshold updating from randomly audited values only.
- Two model back-ends: one hosted API model and one open-weight model.
- Evaluation on a public benchmark plus 50–100 owner-annotated papers; a 5–10 person user study.

### Out of scope
- Training or fine-tuning models.
- Scanned PDFs, OCR, handwriting, values only in figures.
- Searching or screening papers; risk-of-bias assessment.
- Non-English papers; domain-specialised versions.
- Accounts, payments, production hosting.
- Guarantees under strong shift between calibration papers and new papers (documented as a limitation).

---

## 4. System architecture

```
PDF files ──► [1 Document processing] ──► page text + word boxes + sections
                                                │
Field specs ─────────────────────────────────► [2 Extraction] ──► k sampled answers per field
                                                │                     (value + quoted evidence + logprobs)
                                                ▼
                                         [3 Scoring] ──► one candidate value + confidence score per field
                                                │
Verified calibration records ──────────► [4 Calibration] ──► threshold λ per field group (or "not certifiable")
                                                │
                                                ▼
                                         [5 Decision] ──► ACCEPT / FLAG / NOT_CERTIFIABLE
                                                │
                                                ▼
                                   [6 Review UI + audit] ──► corrections, random audits
                                                │
                              random audits only ▼
                                     calibration store (append) ──► recalibrate
```

---

## 5. Statistical core (must be implemented exactly)

### 5.1 Definitions
- An **item** is one (paper, field) pair.
- Each item has a candidate value `v̂`, a score `s ∈ [0, 1]` (higher = more confident) and, when verified, a label `y ∈ {0, 1}` where `y = 1` means **wrong** (see Section 6.4 for matching rules). A missing value that the model reports as "not reported", when the paper truly does not report it, counts as correct.
- For a threshold λ, accept items with `s ≥ λ`.
- **Selective error** at λ: `r(λ) = P(y = 1 | s ≥ λ)`.

### 5.2 Guarantee
With probability at least `1 − δ` over the calibration set, the chosen threshold `λ̂` satisfies `r(λ̂) ≤ α`, provided calibration items and new items are exchangeable (drawn from the same distribution). Defaults: `α = 0.05`, `δ = 0.1`. The user can set α.

### 5.3 Algorithm (fixed-sequence testing; Learn-then-Test style)
Inputs: calibration pairs `(s_i, y_i)` for one field group, `α`, `δ`, a minimum accepted count `m_min` (default 10).

1. Use a **fixed grid** `Λ` defined in settings before any data is seen (default 0.000 to 1.000 in steps of 0.005), sorted **descending** (strictest first). Do **not** build the grid from calibration scores: a data-dependent grid breaks the fixed-sequence argument.
2. For each λ in that order:
   - `n_λ` = number of calibration items with `s ≥ λ`; `e_λ` = number of those with `y = 1`.
   - If `n_λ < m_min`, continue to the next λ.
   - p-value for H₀: `r(λ) > α`: `p_λ = BinomCDF(e_λ; n_λ, α)` (probability of seeing `e_λ` or fewer errors if the true rate were α).
   - If `p_λ ≤ δ`, mark λ as certified and continue; otherwise **stop**.
3. `λ̂` = the last (lowest) certified λ. If none is certified, return `NOT_CERTIFIABLE` for that field group.

Notes for the implementer:
- The fixed-sequence procedure controls family-wise error at δ without a multiple-testing correction because the order is fixed in advance (Angelopoulos et al., 2025).
- Use `scipy.stats.binom.cdf`. Test edge cases: all-correct calibration, all-wrong, ties in scores.
- Also report the **Clopper–Pearson upper bound** on `r(λ̂)` from calibration for display.

### 5.4 Calibration unit and independence
- **Default: calibrate each field separately.** Each paper then contributes at most one item per field, so calibration items are independent across papers, which the binomial test requires.
- Items from the same paper are **not** independent (a badly parsed PDF causes several errors at once). Therefore pooling across fields is a **fallback only**, used when a field has too few records, and the UI must label the result "pooled (assumes errors are independent across fields)".
- Fallback order: field → field group (`numeric`, `categorical`, `short_text`, `long_text`) → not certifiable.
- `evaluate.py` includes a **clustering check**: compare the variance of per-paper error counts with the binomial variance; report the ratio. A ratio well above 1 is reported as a limitation.

### 5.4a Sample sizes required (state these to users and in the thesis)
Minimum accepted calibration items to certify α at δ = 0.1:

| α | 0 errors | 1 error | 2 errors |
|---|---|---|---|
| 0.05 | 45 | 77 | 105 |
| 0.10 | 22 | 38 | 52 |
| 0.20 | 11 | 18 | 25 |

Generate this table in code (`calibrate.required_n`) rather than hard-coding it, and show it in the Calibrate screen. Expect α = 0.05 to be achievable only on the benchmark or on large audit histories; α = 0.10–0.20 is realistic for the owner-annotated set.

### 5.5 Optional alternative (implement after the default works)
Conformal selection with Benjamini–Hochberg on conformal p-values controls the **expected** false discovery rate rather than a high-probability bound (Jin and Candès, 2023). Expose it as `method="conformal_selection"` and compare in experiments.

### 5.6 Safe updating from human checks
- **Only random audits enter the calibration store.** In each review session the app selects a uniform random sample of items from **all** extracted items (accepted and flagged), at a user-set audit rate (default 5%, minimum 3 items), and asks the user to verify them.
- Corrections made to flagged items the user chose to inspect are saved as data corrections but are **not** added to calibration, because they are not a random sample.
- After each batch of new audit records, recalibrate. Keep a versioned log of thresholds.
- Show in the UI how many audit records each field group has and its current guarantee.

### 5.7 Not-certifiable warning
If a field group returns `NOT_CERTIFIABLE`, show: "The AI is not reliable enough on this field to promise an error rate of α. All values are flagged for checking." Also show the estimated raw error rate on calibration.

---

## 6. Data model

Use Pydantic models; persist with SQLite (via SQLModel or plain `sqlite3`).

```python
class FieldSpec(BaseModel):
    name: str                      # "sample_size"
    description: str               # plain-language instruction to the model
    group: Literal["numeric", "categorical", "short_text", "long_text"]
    allowed_values: list[str] | None = None   # for categorical
    unit: str | None = None
    numeric_tolerance: float = 0.0            # absolute; or use rel_tolerance
    rel_tolerance: float = 0.0

class Paper(BaseModel):
    paper_id: str                  # sha256 of file bytes
    filename: str
    n_pages: int

class SampleAnswer(BaseModel):
    value: str | None              # None means "not reported"
    evidence: str | None           # quoted sentence from the paper
    page_hint: int | None
    mean_logprob: float | None

class Extraction(BaseModel):
    paper_id: str
    field: str
    samples: list[SampleAnswer]
    value: str | None              # chosen candidate
    evidence: str | None
    location: list[dict] | None    # [{"page": int, "bbox": [x0,y0,x1,y1]}]
    signals: dict[str, float]      # agreement, logprob, source_match
    score: float
    decision: Literal["ACCEPT", "FLAG", "NOT_CERTIFIABLE"] | None
    model_id: str
    prompt_version: str

class CalibrationRecord(BaseModel):
    paper_id: str
    field: str
    group: str
    score: float
    wrong: bool
    source: Literal["benchmark", "annotation", "random_audit"]
    created_at: datetime
```

### 6.3 Single-answer rule for fields
Every field must have **exactly one correct answer per paper**. The field description must pin down the question (e.g. "total number of participants randomised", not "sample size"; "country where data were collected; if several, return 'multiple'"). Fields that naturally have several answers (per arm, per outcome, per timepoint) are either split into separate single-answer fields or excluded. The Fields screen warns when a description is ambiguous and links to examples. Without this rule labels are arbitrary and the guarantee is meaningless.

### 6.4 Correctness rules (`is_correct(pred, gold, spec)`)
- **numeric:** parse numbers (handle "1,234", "1.2k", "n = 120", words like "one hundred and twenty" via a small parser); correct if `|pred − gold| ≤ max(abs_tol, rel_tol·|gold|)`.
- **categorical:** normalise case and whitespace; map synonyms from a per-field synonym list; exact match.
- **short_text:** normalise (lowercase, strip punctuation, collapse spaces); correct if exact, or token F1 ≥ 0.8.
- **long_text:** token F1 ≥ 0.6, or an optional LLM-judge with a fixed prompt (must be validated against 50 owner judgements before use; report agreement).
- **not reported:** correct only if gold is also "not reported".
All rules live in one module with unit tests. Thresholds are config values, not magic numbers.

---

## 7. Module specifications

### 7.1 `exga/pdf.py`
- `load_pdf(path) -> Document` with per-page text and word bounding boxes (PyMuPDF `page.get_text("words")`).
- `find_span(document, text) -> list[location]`: locate evidence or value text; try exact match, then normalised match, then fuzzy match (`rapidfuzz`, ratio ≥ 90) over sliding windows. Return an empty list if not found.
- `chunk(document, max_tokens)`: section-aware chunks for long papers.

### 7.2 `exga/llm/`
- `base.py`: `class LLMClient: def generate(prompt, n, temperature, json_schema) -> list[RawResponse]` returning text and, if available, token logprobs.
- `hosted.py`: adapter for a hosted API (configurable; prefer one that returns logprobs). Key from env var.
- `local.py`: adapter for an open-weight instruct model via Hugging Face `transformers` (or vLLM on Kaggle).
- `cache.py`: disk cache keyed by `(model_id, prompt_hash, n, temperature, seed)`.
- Retry with exponential backoff; respect rate limits.

### 7.3 `exga/extract.py`
- Prompt template (versioned) asks for JSON: `{"value": ..., "evidence": "<exact quote>", "page": int|null}` and to return `null` when not reported.
- Run `k` samples (default 5) at temperature 0.7 plus one greedy sample at temperature 0.
- Validate JSON; one repair retry on parse failure; otherwise record a failed sample.
- If the paper is long, run per chunk and merge, keeping answers whose evidence is found in the chunk.

### 7.4 `exga/score.py`
Signals, each in [0, 1]:
- `agreement`: share of samples whose value matches the greedy value under the field's correctness rule.
- `logprob`: `exp(mean token logprob)` of the greedy value tokens, if available; otherwise missing.
- `source_match`: 1 if the evidence quote is found in the PDF (Section 7.1) and contains the value, 0.5 if only the quote is found, 0 otherwise.

Combined score:
- Default: a weighted average of available signals (weights in settings), which needs no training data.
- Optional: a logistic regression fitted on a **separate** training split (never the calibration split), with missing-signal indicators; use only when the training split has at least 200 labelled items, and compare against the default.
The candidate value is the greedy answer.

**Data splits must be disjoint:** score-model training, calibration, and test. Never fit anything on the calibration or test split.

### 7.5 `exga/calibrate.py`
- `fit_threshold(scores, wrong, alpha, delta, m_min) -> ThresholdResult` implementing Section 5.3.
- `ThresholdResult`: `lambda_hat | None`, `certified: bool`, `n_accepted_cal`, `errors_accepted_cal`, `upper_bound`, `method`, `group`, `pooled: bool`.
- `conformal_selection(...)` for Section 5.5.

### 7.6 `exga/decide.py`
- Apply thresholds per group to new extractions: `ACCEPT` if `score ≥ λ̂`, else `FLAG`; `NOT_CERTIFIABLE` if the group has no certified threshold.

### 7.7 `exga/audit.py`
- `draw_audit(extractions, rate, min_n, seed) -> list[item]`: uniform random sample over all items.
- `record_audit(item, is_wrong)` appends a `CalibrationRecord(source="random_audit")`.
- `recalibrate(store) -> dict[group, ThresholdResult]` with a versioned log.

### 7.8 `exga/evaluate.py`
- Metrics on a labelled test set: realised selective error, acceptance rate, coverage of correct values, raw accuracy, per group and per model; 95% CIs by bootstrap over papers.
- Baselines: accept all; fixed cut-off (e.g. 0.8) without calibration; verify all.
- Repeated random splits (default 50) to estimate how often the guarantee is violated (should be ≤ δ).

### 7.9 `exga/export.py`
CSV and XLSX export with columns: paper, field, value, decision, score, evidence, page.

### 7.10 `exga/cli.py` (Typer)
```
exga extract --papers ./pdfs --fields fields.yaml --model hosted
exga calibrate --records cal.jsonl --alpha 0.05 --delta 0.1
exga review-export --out results.xlsx
exga evaluate --config experiments/main.yaml
```

### 7.11 `app/` (Streamlit)
Pages:
1. **Project:** create/open a project (one SQLite DB per project).
2. **Fields:** add fields with name, description, group, tolerance; save as YAML.
3. **Upload and run:** upload PDFs, choose model, run extraction with progress bar.
4. **Calibrate:** import benchmark or annotated records, or start an initial random audit; set α; show per-group status (certified / pooled / not certifiable), counts, and upper bounds.
5. **Review table:** green/amber/grey cells; filter by decision; click a cell to open the PDF page with the highlight (render page with PyMuPDF, draw bbox, show image); edit value.
6. **Audit:** present randomly drawn items one by one with PDF highlight; buttons "correct" / "wrong" (+ corrected value).
7. **Export.**
Use `st.session_state` carefully; all logic in the library.

---

## 8. Repository layout

```
exga/
  __init__.py  pdf.py  extract.py  score.py  calibrate.py  decide.py
  audit.py  evaluate.py  export.py  matching.py  schemas.py  store.py  cli.py
  settings.py  errors.py  messages.py  manifest.py
  llm/  base.py  hosted.py  local.py  cache.py
  prompts/  extract_v1.txt
app/
  Home.py  pages/1_Fields.py  2_Run.py  3_Calibrate.py  4_Review.py  5_Audit.py  6_Export.py
data/
  benchmark/   (download script only; do not commit raw data)
  annotated/   (owner's labelled set: fields.yaml, gold.csv, pdf list)
experiments/
  main.yaml  ablations.yaml  run.py  notebooks/
tests/
  test_matching.py  test_calibrate.py  test_guarantee_sim.py  test_pdf.py
  test_extract_parsing.py  test_audit.py  test_end_to_end.py
docs/
  index.md  method.md  user_guide.md  limitations.md
  adr/  0001-risk-control-method.md  0002-dependencies.md  ...
migrations/
  001_init.sql
pyproject.toml  README.md  LICENSE (MIT)  CITATION.cff  .github/workflows/ci.yml
```

**Stack:** Python 3.11; runtime dependencies as listed and justified in Section 0A.3; `transformers`/`torch` only as the optional `[local]` extra. Development: pytest, hypothesis, mypy, ruff, uv or pip-tools for locking.

---

## 9. Testing

### 9.1 Unit tests
Matching rules, PDF span finding (on a fixture PDF), JSON parsing and repair, threshold algorithm edge cases, audit sampling uniformity, export format.

### 9.2 Guarantee simulation test (mandatory)
Generate synthetic `(score, wrong)` data where the true selective error curve is known (e.g. scores ~ Beta, `P(wrong | s) = 1 − s^γ`). Repeat 1,000 times: draw a calibration set, fit λ̂, compute the true `r(λ̂)` analytically. Assert the violation rate `P(r(λ̂) > α) ≤ δ + 0.02`. Also test that biased (non-random) calibration data can violate the guarantee, to justify Section 5.6.

### 9.3 End-to-end test
Two small fixture PDFs, two fields, a mocked LLM client returning canned answers: run extract → score → calibrate → decide → export, check outputs.

### 9.4 CI
Ruff and pytest on every push. Tests must not call real APIs (use the mock client).

---

## 10. Data

### 10.1 Public benchmark
Yun et al. (2024) released 699 annotated RCT reports with numerical outcomes, code and prompts at `https://github.com/hyesunyun/llm-meta-analysis`. These are text (abstracts and results sections), not PDFs: add a `TextDocument` input path that skips PDF processing and source highlighting. Map their annotations to `FieldSpec`s (numeric fields such as group sizes, event counts, means, SDs). Verify the licence before redistribution; commit only a download script.

### 10.2 Owner-annotated set
- 50–100 open-access PDFs from varied fields (health, education, social science, computing).
- 6–10 fields covering all four groups, e.g. `sample_size` (numeric), `country` (short_text), `study_design` (categorical), `year` (numeric), `main_outcome_measure` (short_text), `primary_result` (long_text).
- Record gold values in `gold.csv` (`paper_id, field, value`, with "NR" for not reported).
- Double-annotate a random 20%; report agreement; resolve disagreements.

### 10.3 Splits
Per dataset, split **by paper**: 30% score-model training, 40% calibration, 30% test. Repeat with 50 random seeds for evaluation.

---

## 11. Experiments

### 11.1 Main questions
1. **Validity:** is realised selective error on test ≤ α, and is the violation rate across splits ≤ δ? (α ∈ {0.05, 0.10, 0.20})
2. **Efficiency:** what share of values is accepted (verification saved), versus the baselines?
3. **Field types:** which groups are certifiable, and at what acceptance rate?
4. **Signals ablation:** agreement only; + logprob; + source match; combined.
5. **Models:** hosted vs open-weight.
6. **Updating:** simulate audits arriving in batches; plot acceptance rate and realised error as audit records accumulate.
7. **Optional:** default method vs conformal selection.

### 11.2 Outputs
- Table: per model × group × α → raw accuracy, acceptance rate, realised error (95% CI), violation rate, certified (yes/no).
- Figures: acceptance vs α; realised vs target error; updating curve.
- All produced by `experiments/run.py` from YAML configs; outputs saved with config hash.

### 11.3 User study
- 5–10 participants (students or researchers); informed consent; anonymous IDs.
- Within-subject design: extract the same fields from two small paper sets, one manually and one with the tool (order counterbalanced).
- Measure time, accuracy against gold, and a short trust/usability questionnaire (e.g. System Usability Scale).
- Report descriptively; no strong claims given the sample size.

---

## 11A. Priority tiers (to keep a solo build finishable)

- **Must have:** PDF processing, hosted-model extraction, three signals with weighted-average score, per-field calibration on a fixed grid, decisions, random audit and recalibration, web app core screens (Fields, Run, Calibrate, Review, Audit, Export), guarantee simulation test, evaluation on both datasets, user study.
- **Should have:** local open-weight model, logistic-regression score, clustering check, PDF highlight rendering for all matches.
- **Could have:** conformal selection comparison, LLM-judge for long text, numbered migrations (a single schema file is acceptable), XLSX export (CSV is enough).

Do not start a "could have" item until every "must have" passes its acceptance check.

## 12. Build phases and acceptance checks

| Phase | Work | Done when |
|---|---|---|
| P0 Setup | Repo, pyproject, lock file, CI (ruff, mypy strict on core, pytest), settings, errors, schemas, mock LLM, ADRs 0001–0002 | CI green; ADRs reviewed by owner |
| P1 Matching and calibration core | `matching.py`, `calibrate.py`, simulation test | Section 9.2 test passes; edge cases covered |
| P2 PDF processing | Load, find spans, chunk | Fixture tests pass; highlights render correctly |
| P3 Extraction | LLM clients, cache, prompts, parsing | 10 real PDFs extract with < 5% parse failures |
| P4 Scoring and decisions | Signals, score model, decide | End-to-end test passes with mock client |
| P5 Data | Benchmark loader; annotated set | Gold files validated; splits reproducible |
| P6 Audit and updating | Random audit, store, recalibration log | Unit tests pass; simulation shows biased data breaks guarantee, random audit does not |
| P7 Web app | All pages | Owner completes upload → review → audit → export unaided |
| P8 Experiments | Section 11.1 | All tables and figures generated from configs |
| P9 User study | Section 11.3 | Data collected and summarised |
| P10 Packaging and docs | README, user guide, method, limitations, release | `pip install` works from a clean environment; app runs from README steps |
| P11 Thesis support | Export figures/tables; method write-up | Owner signs off |

---

## 13. Risks and how to handle them

| Risk | Handling |
|---|---|
| Field error too high to certify | Expected for some numeric fields; report as NOT_CERTIFIABLE with raw error rate (Kotte, 2026) |
| Calibration and new papers differ | Document; show per-group audit counts; encourage audits on each new batch |
| API cost / rate limits | Cache all calls; small k; use open-weight model for bulk runs |
| Logprobs unavailable | Score model handles missing signals |
| PDF text extraction errors (columns, tables) | Use PyMuPDF block ordering; record parse issues; exclude badly parsed PDFs from evaluation with a stated rule |
| Matching rules too strict or loose | Validate against 50 owner judgements; report agreement |
| Small user study | Report descriptively |

---

## 14. Definition of done

- Library installable, tested (guarantee simulation passing), documented.
- Web app runs locally from the README and supports the full workflow.
- Experiments reproducible from configs; results tables and figures saved.
- User study summarised.
- Limitations documented: exchangeability assumption, English text PDFs only, field-dependent certifiability.
- Release tagged on GitHub with licence and citation file.

---

## 15. Thesis mapping (five chapters)

1. **Introduction:** problem, aim, objectives, scope, significance.
2. **Literature review:** LLM data extraction; uncertainty quantification for LLMs; conformal and risk-controlled selective prediction; tools.
3. **Methodology:** system design (Sections 4–7), statistical core (Section 5), data (Section 10), experiments and user study (Section 11).
4. **Results and discussion:** validity, efficiency, field types, ablations, models, updating, user study.
5. **Conclusions and recommendations:** contributions, limitations, future work.

---

## 16. References

- Angelopoulos, A.N., Bates, S., Candès, E.J., Jordan, M.I. and Lei, L. (2025). Learn then test: calibrating predictive algorithms to achieve risk control. *The Annals of Applied Statistics*, 19(2), 1641–1662.
- Angelopoulos, A.N., Bates, S., Fisch, A., Lei, L. and Schuster, T. (2024). Conformal risk control. *ICLR*.
- Bates, S., Angelopoulos, A.N., Lei, L., Malik, J. and Jordan, M.I. (2021). Distribution-free, risk-controlling prediction sets. *Journal of the ACM*, 68(6).
- Bianchi, J., Hirt, J., Vogt, M. et al. (2025). Data extractions using a large language model (Elicit) and human reviewers in randomized controlled trials: a systematic comparison. *Cochrane Evidence Synthesis and Methods*.
- Bouchard, D. et al. (2026). UQLM: a Python package for uncertainty quantification in large language models. *JMLR*, 27(13).
- Gartlehner, G., Kugley, S., Crotty, K. et al. (2025). Artificial intelligence-assisted data extraction with a large language model: a study within reviews. *medRxiv*, doi:10.1101/2025.03.20.25324350.
- Geifman, Y. and El-Yaniv, R. (2017). Selective classification for deep neural networks. *NeurIPS*.
- Goh, H.W. and Mueller, J. (2026). Real-time trustworthiness scoring for LLM structured outputs and data extraction. arXiv:2603.18014.
- Jin, Y. and Candès, E.J. (2023). Selection by prediction with conformal p-values. *JMLR*, 24(244).
- Konet, A. et al. (2024). Performance of two large language models for data extraction in evidence synthesis. *Research Synthesis Methods*, 15(5), 818–824.
- Kotte, V. (2026). When can conformal risk control certify LLM outputs? Bounds, impossibility, and adaptation for structured generation. arXiv:2606.29054.
- Li, L., Mathrani, A. and Susnjak, T. (2026). What level of automation is "good enough"? A benchmark of large language models for meta-analysis data extraction. *Research Synthesis Methods*.
- Manakul, P., Liusie, A. and Gales, M.J.F. (2023). SelfCheckGPT. *EMNLP*.
- Shrestha, M. and Kim, E. (2026). Conformal prediction for risk-controlled medical entity extraction across clinical domains. arXiv:2603.00924.
- Yun, H.S., Pogrebitskiy, D., Marshall, I.J. and Wallace, B.C. (2024). Automatically extracting numerical results from randomized controlled trials with large language models. *Machine Learning for Healthcare*, PMLR 252.
