"""typed records that cross module boundaries (spec sections 6 and 7.5).

every model is frozen and rejects unknown fields: pipeline steps return new records instead
of mutating shared ones, which keeps the pure core free of hidden state, and a misspelt
field fails loudly instead of being dropped. sequences are tuples for the same reason.
to change a record, validate a new one; `model_copy(update=...)` skips validation.
"""

from typing import Annotated, Literal, Self, get_args

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

FieldGroup = Literal["numeric", "categorical", "short_text", "long_text"]
Decision = Literal["ACCEPT", "FLAG", "NOT_CERTIFIABLE"]
RecordSource = Literal["benchmark", "annotation", "random_audit"]
# conformal selection (spec 5.5) joins this literal when it is implemented. its bound holds
# in expectation, not with probability 1 - delta, so user messages must change with it.
RiskMethod = Literal["fixed_sequence"]

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
Count = Annotated[int, Field(ge=0)]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# sha256 of the file bytes, so identical files always share one id (spec 0A.1)
PaperId = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
FieldName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)]
# 1-based PDF page index, which can differ from the page number printed on the page
PageNumber = Annotated[int, Field(ge=1)]

# a categorical field with one allowed value has a constant answer, not a question
_MIN_CATEGORIES = 2


class _Record(BaseModel):
    """configuration shared by every record; it carries no behaviour.

    a base class rather than a shared ConfigDict variable, because the pydantic mypy plugin
    only sees `frozen=True` in a class body, and it must see it to reject mutation statically.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", use_attribute_docstrings=True)


class FieldSpec(_Record):
    """one user-defined field to extract.

    the description must pin the question to exactly one correct answer per paper
    (spec 6.3); otherwise gold labels, and so the guarantee, are arbitrary.
    """

    name: FieldName
    description: NonEmptyText
    group: FieldGroup
    allowed_values: tuple[NonEmptyText, ...] | None = None
    unit: str | None = None
    numeric_tolerance: float = Field(default=0.0, ge=0.0)
    """absolute tolerance for numeric fields, in the field's unit."""
    rel_tolerance: float = Field(default=0.0, ge=0.0)
    """relative tolerance for numeric fields, as a fraction of the gold value."""

    @model_validator(mode="after")
    def _check_options_fit_group(self) -> Self:
        has_numeric_options = (
            self.unit is not None or self.numeric_tolerance > 0 or self.rel_tolerance > 0
        )
        if self.group != "numeric" and has_numeric_options:
            raise ValueError(f"unit and tolerances apply only to numeric fields, not {self.group}")
        if self.group == "categorical":
            if self.allowed_values is None or len(set(self.allowed_values)) < _MIN_CATEGORIES:
                raise ValueError("categorical fields need at least two distinct allowed_values")
        elif self.allowed_values is not None:
            raise ValueError(f"allowed_values apply only to categorical fields, not {self.group}")
        return self


class Paper(_Record):
    """a source document known to the pipeline."""

    paper_id: PaperId
    filename: NonEmptyText
    n_pages: int = Field(ge=1)


class SampleAnswer(_Record):
    """one sampled model answer for a field; value None means "not reported"."""

    value: str | None
    evidence: str | None
    """quote that the model says supports the value; unverified until source matching."""
    page_hint: PageNumber | None = None
    mean_logprob: float | None = Field(default=None, le=0.0)
    """mean token log-probability of the answer, when the back-end exposes logprobs."""


class SpanLocation(_Record):
    """a rectangle of text on one PDF page, in PDF points with the origin at the top left."""

    page: PageNumber
    bbox: tuple[float, float, float, float]
    """(x0, y0, x1, y1) with x0 <= x1 and y0 <= y1."""

    @model_validator(mode="after")
    def _check_corners_are_ordered(self) -> Self:
        x0, y0, x1, y1 = self.bbox
        if x0 > x1 or y0 > y1:
            raise ValueError(f"bbox corners out of order: {self.bbox}")
        return self


class Signals(_Record):
    """confidence signals for one item, each in [0, 1] (spec 7.4); None when unavailable."""

    agreement: Probability
    """share of stochastic samples whose value matches the greedy value."""
    logprob: Probability | None = None
    """exp(mean token logprob) of the greedy value; None when the back-end has no logprobs."""
    source_match: Probability | None = None
    """1 if the evidence is found and contains the value, 0.5 if only found, 0 if not found."""


class Extraction(_Record):
    """the scored candidate value for one item (paper, field) and how it was produced."""

    paper_id: PaperId
    field: FieldName
    samples: tuple[SampleAnswer, ...]
    value: str | None
    """the greedy answer, which is always the candidate; None means "not reported"."""
    evidence: str | None
    location: tuple[SpanLocation, ...] = ()
    """where the evidence was found; empty when not found or the source is not a PDF."""
    signals: Signals
    score: Probability
    decision: Decision | None = None
    """set by the decision step; None until thresholds have been applied."""
    model_id: NonEmptyText
    prompt_version: NonEmptyText


class CalibrationRecord(_Record):
    """one verified item used to certify thresholds; never changed once written (spec 5.6)."""

    paper_id: PaperId
    field: FieldName
    group: FieldGroup
    score: Probability
    wrong: bool
    """True when the extracted value fails the field's correctness rule (spec 6.4)."""
    source: RecordSource
    created_at: AwareDatetime
    """timezone-aware, so records written on different machines order correctly."""


class ThresholdResult(_Record):
    """outcome of certifying one calibration unit: a field, or a field group when pooled.

    when certified, with probability at least 1 - delta over the draw of calibration records,
    the error rate among items scoring >= lambda_hat is at most alpha, provided new items are
    exchangeable with calibration items (spec 5.2). messages.py words every claim shown to
    users from these fields, so they carry everything that wording needs.
    """

    group: NonEmptyText
    """the calibration unit's name: a field name, or a field-group name when pooled."""
    method: RiskMethod
    pooled: bool
    """True when several fields' records were combined; assumes their errors are independent."""
    alpha: float = Field(gt=0.0, lt=1.0)
    delta: float = Field(gt=0.0, lt=1.0)
    n_cal: Count
    """calibration records in this unit."""
    errors_cal: Count
    """wrong values among them; errors_cal / n_cal is the raw error rate shown to users."""
    certified: bool
    lambda_hat: Probability | None
    """lowest certified grid threshold; None when not certifiable."""
    n_accepted_cal: Count
    """calibration records scoring >= lambda_hat; 0 when not certifiable."""
    errors_accepted_cal: Count
    upper_bound: Probability | None
    """clopper-pearson upper bound on the error at lambda_hat, for display only."""

    @model_validator(mode="after")
    def _check_counts_and_certification_agree(self) -> Self:
        if self.errors_cal > self.n_cal or self.n_accepted_cal > self.n_cal:
            raise ValueError("counts exceed the number of calibration records")
        if self.errors_accepted_cal > min(self.n_accepted_cal, self.errors_cal):
            raise ValueError("accepted errors exceed accepted items or total errors")
        if self.pooled and self.group not in get_args(FieldGroup):
            raise ValueError(f"a pooled result must name a field group, got {self.group!r}")
        if self.certified:
            if self.lambda_hat is None or self.upper_bound is None or self.n_accepted_cal == 0:
                raise ValueError(
                    "a certified result needs lambda_hat, upper_bound and accepted items"
                )
        elif (self.lambda_hat, self.upper_bound, self.n_accepted_cal) != (None, None, 0):
            raise ValueError("an uncertified result has no threshold, bound or accepted items")
        return self


class TokenLogprob(_Record):
    """one generated token and its log-probability under the model."""

    token: str
    logprob: float = Field(le=0.0)


class RawResponse(_Record):
    """one completion from a model back-end, before parsing; token counts feed cost tracking."""

    text: str
    token_logprobs: tuple[TokenLogprob, ...] | None
    """per-token log-probabilities; None when the back-end does not expose them."""
    input_tokens: Count
    output_tokens: Count
