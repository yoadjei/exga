# ADR 0002: dependency set, and no LLM orchestration frameworks

- **Status:** accepted 2026-11-25 (the owner delegated these decisions)
- **Date:** 2026-11-25
- **Spec:** sections 0A.2, 0A.3, 8

## Context

Every runtime dependency must earn its place (spec 0A.3). The owner has to be able to explain
each layer to examiners, the core must install quickly on a laptop and run in under 1 GB of
RAM, and the retry, parsing and caching rules (spec 0A.2, 7.2–7.3) must live in project code
where they can be read and tested.

## Decision 1: call model APIs directly with httpx behind `LLMClient`

| Option | For | Against |
|---|---|---|
| LangChain or LlamaIndex | adapters, templates, parsers and retries ready-made | large, fast-moving dependency tree; retries and parsing run inside framework code, where the spec 0A.2 rules (retry only transient errors, one explicit repair step) cannot be seen or tested; examiners read framework glue instead of the method |
| Provider SDK inside `hosted.py` | typed responses, maintained by the vendor | ties the code to one vendor; built-in retries must be switched off to meet spec 0A.2; a second provider means a second SDK |
| **httpx behind the `LLMClient` protocol** | one dependency for any HTTP API; timeouts, retries and rate limiting are project code with tests; `httpx.MockTransport` tests adapters offline | we map request and response JSON ourselves and track API changes |

**Chosen:** httpx. Revisit if the chosen hosted API needs features that are awkward over raw
HTTP (streaming, structured-output negotiation); then use that provider's SDK inside
`hosted.py` only, with its retries disabled.

## Decision 2: the runtime set, and when each package enters

A package enters `pyproject.toml` in the commit whose code first imports it, so each diff shows
a dependency next to its reason. Lower bounds live in `pyproject.toml`, exact versions in
`uv.lock`, and CI installs with `--locked`.

| Package | Role | Enters | Licence | Rejected alternative |
|---|---|---|---|---|
| pydantic | typed records; validates LLM JSON | P0 | MIT | stdlib dataclasses plus jsonschema: validation split across two mechanisms |
| pydantic-settings | `Settings` from environment and `.env` | P0 | MIT | hand-written environment parsing |
| numpy | vectorised calibration: sort once, cumulative sums | P1 | BSD-3 | plain Python: the budget of 10,000 items in under 1 s (spec 0A.5) is easiest to meet vectorised |
| scipy | `binom.cdf`; Clopper–Pearson via `beta.ppf` | P1 | BSD-3 | hand-written CDFs: numerical accuracy is part of the guarantee |
| pymupdf | text, word boxes, page rendering | P2 | **AGPL-3.0** | pdfplumber (MIT; pure-Python parsing via pdfminer.six; benchmark it if AGPL is unacceptable); pypdf (BSD; no word-level box API) |
| rapidfuzz | fuzzy span search over sliding windows | P2 | MIT | stdlib `difflib`: pure Python |
| httpx | hosted API calls | P3 | BSD-3 | requests: no default timeout, no built-in mock transport |
| pyyaml | `fields.yaml` and experiment configs | P3 | MIT | not in the spec 0A.3 list, but spec 6 and 11.2 need YAML files; the stdlib cannot write TOML (the app saves fields), and JSON has no comments |
| typer | CLI (spec 7.10) | with the first command | MIT | argparse: more code for subcommands and help |
| pandas | export and evaluation tables | P4 | BSD-3 | stdlib csv; pandas arrives with streamlit anyway; never imported by the pure core |
| openpyxl | XLSX export (could-have) | when built; lazy import | MIT | CSV only |
| scikit-learn | logistic score model (should-have) | when built | BSD-3 | a small `scipy.optimize` fit; decide when built |
| streamlit | web app | P7 | Apache-2.0 | its own ADR (spec 0A.7, item 5) |
| transformers, torch | optional `[local]` extra | when built | Apache-2.0, BSD-3 | none; lazy imports keep the core install small |

Dev tools: uv (environments and lock file), hatchling (build backend), ruff, mypy with the
pydantic plugin, pytest, pytest-cov, and hypothesis from P1.

## Consequences

- The pure core (matching, score, calibrate, decide, evaluate, audit) is meant to import only
  numpy, scipy and pydantic. Any other import there needs a line in this ADR.
- PyMuPDF is AGPL-3.0. exga's own code stays MIT, but anyone who distributes exga together
  with PyMuPDF, or runs a modified version as a network service, must meet the AGPL terms.
  **Decided: keep PyMuPDF.** It is the only candidate with word boxes and page rendering in
  one package, the spec names it, and exga is open source anyway. The README states the
  dependency's licence.
- pyyaml is an addition to the spec's list.
- streamlit brings pyarrow and pandas, the largest part of the install, to library users too.
  Revisit if install time hurts on Kaggle or a laptop: move the app into an `[app]` extra.
