"""runtime configuration: every tunable number in exga is a named, documented setting here.

values come from defaults, then an optional env file, then ``EXGA_`` environment variables,
which win. nested groups use a double underscore, e.g. ``EXGA_CALIBRATION__ALPHA=0.1``.
the shell builds one `Settings` with `load_settings` and passes it down explicitly; no module
reads settings from global state.

a settings group is added in the phase that first uses it, so nothing here is speculative.
"""

import math
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from exga.errors import ConfigError


class CalibrationSettings(BaseModel):
    """parameters of the risk-control guarantee (spec section 5), fixed before seeing data."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    """target maximum error rate among accepted values."""

    delta: float = Field(default=0.1, gt=0.0, lt=1.0)
    """allowed probability that the certified bound fails; the stated confidence is 1 - delta."""

    min_accepted: int = Field(default=10, ge=1)
    """m_min: lower bound on the starting floor. thresholds accepting fewer items than
    max(min_accepted, required_n(alpha, delta, 0)) are skipped (ADR 0004)."""

    grid_step: float = Field(default=0.005, gt=0.0, le=1.0)
    """spacing of the fixed threshold grid over [0, 1]; must divide 1 exactly."""

    @field_validator("grid_step")
    @classmethod
    def _check_step_divides_unit_interval(cls, step: float) -> float:
        # the grid must include both 1 (strictest) and 0 (accept everything), so the
        # candidate thresholds cover the whole score range
        if not math.isclose(round(1.0 / step) * step, 1.0):
            raise ValueError(f"grid_step must divide 1 exactly, got {step}")
        return step


class MatchingSettings(BaseModel):
    """thresholds of the correctness rules for text fields (spec 6.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    short_text_min_f1: float = Field(default=0.8, gt=0.0, le=1.0)
    """token F1 at or above which a short_text value counts as correct when not identical."""

    long_text_min_f1: float = Field(default=0.6, gt=0.0, le=1.0)
    """token F1 at or above which a long_text value counts as correct."""


class DocumentSettings(BaseModel):
    """how documents are read and searched (spec 7.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    span_min_similarity: float = Field(default=0.9, gt=0.0, le=1.0)
    """fuzzy similarity (rapidfuzz ratio / 100) at or above which quoted text counts as found."""

    min_text_chars: int = Field(default=200, ge=0)
    """a PDF with fewer extractable characters is treated as scanned, which is out of scope."""

    render_zoom: float = Field(default=1.5, gt=0.0, le=4.0)
    """page rendering scale for highlights: 1.5 gives 108 dpi, legible without large images."""


class AuditSettings(BaseModel):
    """random audits, the only source of new calibration records (spec 5.6, ADR 0009)."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    rate: float = Field(default=0.05, gt=0.0, le=1.0)
    """share of all extracted items drawn for checking in each review session."""

    min_items: int = Field(default=3, ge=1)
    """smallest audit batch, so small projects still collect records."""

    seed: int = 0
    """base seed of audit draws; batch k uses seed + k, so a project's draws can be replayed."""


class SplitSettings(BaseModel):
    """shares of papers in each split (spec 10.3); the test split gets the rest."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    train: float = Field(default=0.3, ge=0.0, lt=1.0)
    """share of papers for fitting a score model; never used for thresholds."""

    calibration: float = Field(default=0.4, gt=0.0, lt=1.0)
    """share of papers for certifying thresholds."""

    repetitions: int = Field(default=50, ge=1)
    """random splits per experiment, to estimate how often the guarantee fails."""

    double_annotation: float = Field(default=0.2, gt=0.0, le=1.0)
    """share of annotated papers labelled by a second person, to measure agreement."""

    @model_validator(mode="after")
    def _check_test_split_is_left(self) -> Self:
        if self.train + self.calibration >= 1.0:
            raise ValueError("train + calibration must leave a share for the test split")
        return self


class ScoreSettings(BaseModel):
    """weights of the default combined score, a weighted average of the signals (spec 7.4).

    a signal that is unavailable for an item drops out and the other weights are rescaled.
    agreement is always available, so its weight must be positive.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    agreement_weight: float = Field(default=1.0, gt=0.0)
    """weight of sample agreement."""

    logprob_weight: float = Field(default=1.0, ge=0.0)
    """weight of the greedy value's token probability; 0 ignores it."""

    source_weight: float = Field(default=1.0, ge=0.0)
    """weight of the evidence check against the paper; 0 ignores it."""


class ExtractionSettings(BaseModel):
    """how answers are sampled from the model (spec 7.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    samples: int = Field(default=5, ge=1)
    """k: sampled answers per chunk, besides the greedy one."""

    temperature: float = Field(default=0.7, gt=0.0, le=2.0)
    """temperature of the k sampled answers; the greedy answer always uses 0."""

    seed: int = 0
    """sampling seed sent to back-ends that support one, so reruns can reproduce answers."""

    max_chunk_tokens: int = Field(default=24_000, ge=1_000)
    """most paper text per prompt, in estimated tokens; longer papers are split and merged."""

    prompt_version: str = Field(default="extract_v1", pattern=r"^[a-z0-9_]+$")
    """folder under exga/prompts/ holding the prompt files; stored with every extraction."""

    workers: int = Field(default=4, ge=1)
    """items extracted in parallel; the rate limiter still caps requests (spec 0A.5)."""


class HostedSettings(BaseModel):
    """an OpenAI-compatible chat-completions endpoint, hosted or local (ADR 0006)."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)

    base_url: str = "https://api.openai.com/v1"
    """endpoint root; a local vLLM or llama.cpp server is e.g. http://localhost:8000/v1."""

    model: str | None = None
    """model name sent with each request; required before the client can be built."""

    api_key: SecretStr | None = None
    """bearer token; never logged. leave unset for local servers that need none."""

    timeout_seconds: float = Field(default=120.0, gt=0.0)
    """per-request timeout; long papers make long prompts."""

    max_retries: int = Field(default=5, ge=0)
    """retries after the first attempt, for transient failures only."""

    backoff_initial_seconds: float = Field(default=1.0, gt=0.0)
    """wait before the first retry; doubles per retry, with jitter."""

    backoff_max_seconds: float = Field(default=60.0, gt=0.0)
    """cap on any single wait, including a server's Retry-After."""

    requests_per_minute: float = Field(default=60.0, gt=0.0)
    """sustained request rate shared by all worker threads."""

    burst: int = Field(default=4, ge=1)
    """requests that may start at once; matches the default worker count."""

    supports_n: bool = True
    """endpoint returns n choices per request; otherwise n requests are sent."""

    logprobs: bool = True
    """request token logprobs, needed for the logprob signal (spec 7.4)."""

    structured_output: bool = True
    """send the answer JSON schema as response_format; parsing validates either way."""

    max_output_tokens: int = Field(default=512, ge=1)
    """completion length cap; an answer is a short JSON object."""

    output_tokens_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    """name of the length parameter; newer OpenAI models accept only max_completion_tokens."""

    input_price_per_million: float | None = Field(default=None, ge=0.0)
    """USD per million prompt tokens, for cost accounting."""

    output_price_per_million: float | None = Field(default=None, ge=0.0)
    """USD per million completion tokens, for cost accounting."""

    budget_usd: float | None = Field(default=None, gt=0.0)
    """stop sending requests once a run has spent this much; needs both prices."""

    @model_validator(mode="after")
    def _check_budget_is_measurable(self) -> Self:
        priced = (
            self.input_price_per_million is not None and self.output_price_per_million is not None
        )
        if self.budget_usd is not None and not priced:
            raise ValueError(
                "budget_usd needs input_price_per_million and output_price_per_million"
            )
        return self


class Settings(BaseSettings):
    """all exga settings. build with `load_settings`, then pass explicitly."""

    model_config = SettingsConfigDict(
        env_prefix="EXGA_",
        env_nested_delimiter="__",
        frozen=True,
        extra="forbid",
        use_attribute_docstrings=True,
    )

    calibration: CalibrationSettings = Field(default_factory=CalibrationSettings)
    """risk-control parameters."""

    matching: MatchingSettings = Field(default_factory=MatchingSettings)
    """correctness-rule thresholds."""

    document: DocumentSettings = Field(default_factory=DocumentSettings)
    """document reading and search."""

    extraction: ExtractionSettings = Field(default_factory=ExtractionSettings)
    """answer sampling."""

    score: ScoreSettings = Field(default_factory=ScoreSettings)
    """combined-score weights."""

    splits: SplitSettings = Field(default_factory=SplitSettings)
    """data splits for experiments."""

    audit: AuditSettings = Field(default_factory=AuditSettings)
    """random audits."""

    hosted: HostedSettings = Field(default_factory=HostedSettings)
    """the chat-completions model back-end."""


def load_settings(env_file: Path | None = None) -> Settings:
    """return settings from defaults, an optional env file and ``EXGA_`` environment variables.

    raises ConfigError when env_file is given but missing, or when any value is invalid or
    unknown; the message names each offending setting, e.g. ``calibration.alpha``.
    """
    if env_file is not None and not env_file.is_file():
        raise ConfigError(f"settings file not found: {env_file}")
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigError(f"invalid settings: {problems}") from exc
