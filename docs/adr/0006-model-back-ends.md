# ADR 0006: one chat-completions adapter for hosted and local models

- **Status:** accepted 2026-11-25 (the owner delegated this decision)
- **Date:** 2026-11-25
- **Spec:** sections 0A.5, 7.2, 7.3, 7.4; code: `exga/llm/hosted.py`

## Context

The spec asks for a hosted adapter that preferably returns token logprobs, and a local adapter
for an open-weight model, behind the small `LLMClient` protocol. Two signals in spec 7.4 shape
the choice:

- `logprob` needs per-token log-probabilities of the greedy answer;
- `agreement` needs k samples at temperature 0.7 plus one greedy sample at temperature 0, so
  the back-end must accept a temperature.

## Options

| Option | logprobs | temperature 0 / 0.7 | Cost to the owner | Verdict |
|---|---|---|---|---|
| Anthropic Messages API (the only key on the build machine) | no | rejected with an error on current models | paid | rejected: two of the three spec 7.4 inputs are unavailable; the method would silently become agreement-at-default-temperature plus source match |
| OpenAI-compatible `/chat/completions` over httpx | yes (`logprobs: true`) | yes | paid when hosted, free when local | **chosen** |
| In-process `transformers` adapter (`local.py` in the spec) | yes | yes | free; needs `torch` (≈2 GB) and a GPU to be usable | deferred: vLLM and llama.cpp both serve the same model behind an OpenAI-compatible endpoint with logprobs |

## Decision

`exga/llm/hosted.py` implements one client for the OpenAI chat-completions wire format. The
base URL, model and API key are settings (`EXGA_HOSTED__BASE_URL`, `EXGA_HOSTED__MODEL`,
`EXGA_HOSTED__API_KEY`), so the same code talks to:

- OpenAI or any compatible hosted provider, for the hosted condition;
- a vLLM or llama.cpp server on the same machine or a Kaggle notebook, for the open-weight
  condition. Paper text then never leaves that machine, which meets the privacy rule in 0A.5.

Provider differences are flags, not code paths: whether the endpoint accepts `n > 1`
(otherwise exga sends n requests with seeds `seed, seed + 1, ...` so samples differ), whether
it returns logprobs, whether it accepts a `json_schema` response format, and the name of the
output-length parameter.

The client owns the operational rules of 0A.5 and 7.2:

- retries only transient failures (connection errors, timeouts, HTTP 408, 429, 5xx) with
  capped exponential backoff and jitter, honouring `Retry-After`; any other 4xx fails at once
  with the provider's message;
- a token-bucket limit on requests per minute, shared by all worker threads;
- a usage meter: tokens in and out per run and, when prices are configured, cost, with a
  per-run budget that refuses new requests once spent (`BudgetExceededError`).

## Consequences

- The method runs unchanged on hosted and local models; experiments compare them by changing
  settings only.
- No model runs inside the exga process, so the core install stays small and the `[local]`
  extra is not needed. If a back-end without an OpenAI-compatible server is ever required, it
  gets its own adapter behind `LLMClient`.
- A Claude adapter is possible later through the official Anthropic SDK; its extractions would
  have no `logprob` signal and no greedy sample, and the thesis must report that as a
  different condition, not the same method.
- P3's acceptance check (10 real PDFs) needs either an API key for a compatible provider or a
  local model server. Neither exists on the build machine, so that check waits for the owner.
