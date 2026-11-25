"""confidence signals and the combined score of one item (spec 7.4). pure functions.

the candidate value is always the greedy answer. three signals in [0, 1] describe how far to
trust it; the default score is their weighted average, which needs no training data.
"""

import math

from exga.document import locate, match_locations, matched_text
from exga.matching import contains_value, values_match
from exga.schemas import (
    Document,
    Extraction,
    FieldSamples,
    FieldSpec,
    SampleAnswer,
    Signals,
    SpanLocation,
)
from exga.settings import MatchingSettings, ScoreSettings, Settings

# source_match levels (spec 7.4)
SOURCE_STATES_VALUE = 1.0
SOURCE_FOUND_ONLY = 0.5
SOURCE_NOT_FOUND = 0.0


def agreement(item: FieldSamples, spec: FieldSpec, rules: MatchingSettings) -> float:
    """share of sampled answers whose value matches the greedy value under the field's rule.

    failed samples count and match nothing; so does every sample when the greedy answer
    failed. two "not reported" answers match.
    """
    total = len(item.samples) + item.failed_samples
    if item.greedy is None or total == 0:
        return 0.0
    greedy_value = item.greedy.value
    matches = sum(values_match(s.value, greedy_value, spec, rules) for s in item.samples)
    return matches / total


def logprob_signal(greedy: SampleAnswer | None) -> float | None:
    """exp(mean token logprob) of the greedy value: its geometric-mean token probability."""
    if greedy is None or greedy.mean_logprob is None:
        return None
    return math.exp(greedy.mean_logprob)


def source_match(
    document: Document,
    greedy: SampleAnswer | None,
    spec: FieldSpec,
    settings: Settings,
) -> tuple[float | None, tuple[SpanLocation, ...]]:
    """check the greedy answer's evidence against the paper; return the signal and highlights.

    1.0 when the quote is found and the text found in the paper states the value, 0.5 when
    the quote is found but does not state it, 0.0 when it is not found or missing. the check
    reads the paper's own text, so a fuzzy match cannot hide a changed number. None for a
    "not reported" answer, which has nothing to find. highlights cover the matched text.
    """
    if greedy is None:
        return SOURCE_NOT_FOUND, ()
    if greedy.value is None:
        return None, ()
    if greedy.evidence is None:
        return SOURCE_NOT_FOUND, ()
    matches = locate(
        document, greedy.evidence, min_similarity=settings.document.span_min_similarity
    )
    if not matches:
        return SOURCE_NOT_FOUND, ()
    stating = [
        match
        for match in matches
        if contains_value(matched_text(document, match), greedy.value, spec, settings.matching)
    ]
    chosen = (stating or matches)[0]
    level = SOURCE_STATES_VALUE if stating else SOURCE_FOUND_ONLY
    return level, tuple(match_locations(document, chosen))


def combine(signals: Signals, weights: ScoreSettings) -> float:
    """weighted average of the available signals; unavailable ones drop out."""
    weighted = [
        (signals.agreement, weights.agreement_weight),
        (signals.logprob, weights.logprob_weight),
        (signals.source_match, weights.source_weight),
    ]
    available = [(value, weight) for value, weight in weighted if value is not None and weight > 0]
    total = math.fsum(weight for _, weight in available)
    return math.fsum(value * weight for value, weight in available) / total


def score_item(
    item: FieldSamples, document: Document, spec: FieldSpec, settings: Settings
) -> Extraction:
    """turn one item's answers into a scored candidate, without a decision yet."""
    greedy = item.greedy
    source, locations = source_match(document, greedy, spec, settings)
    signals = Signals(
        agreement=agreement(item, spec, settings.matching),
        logprob=logprob_signal(greedy),
        source_match=source,
    )
    return Extraction(
        paper_id=item.paper_id,
        field=item.field,
        samples=item.samples,
        value=None if greedy is None else greedy.value,
        failed=greedy is None,
        evidence=None if greedy is None else greedy.evidence,
        location=locations,
        signals=signals,
        score=0.0 if greedy is None else combine(signals, settings.score),
        model_id=item.model_id,
        prompt_version=item.prompt_version,
    )
