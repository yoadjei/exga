"""correctness rules: whether an extracted value counts as equal to the gold value (spec 6.4).

pure functions. None means "not reported" throughout, and matches only another None.
`is_correct` judges a prediction against a gold label and treats a malformed gold label as an
error; `values_match` compares any two values, e.g. two model samples, and never raises on
what a model wrote.
"""

import re
import unicodedata
from collections import Counter
from decimal import Decimal

from exga.errors import ConfigError
from exga.schemas import FieldSpec
from exga.settings import MatchingSettings

# digits with optional thousands separators, decimals and exponent, then an optional scale.
# the sign (hyphen, unicode minus u+2212 or en dash u+2013, all used for minus in papers)
# counts only when it does not follow a word character, so "COVID-19" reads as 19.
# "m" is not a scale suffix: in papers "12 m" is far more often metres or months than millions.
_NUMBER = re.compile(
    r"""
    (?:(?<![\w.])(?P<sign>[-\u2212\u2013]))?
    (?P<digits>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)
    (?:[eE](?P<exponent>[-+]?\d+))?
    (?:(?P<suffix>k)\b|\s*(?P<word>thousand|million|billion)\b)?
    """,
    re.VERBOSE | re.IGNORECASE,
)
_SCALES = {"k": 1_000, "thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
_UNIT_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}  # fmt: skip
_TENS_WORDS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip


def normalise_text(text: str) -> str:
    """return text lowercased, with punctuation dropped and whitespace collapsed (spec 6.4).

    dashes, underscores and slashes become spaces, so "case-control" and "case_control" both
    read "case control"; other punctuation is removed, so "U.S.A." reads "usa".
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    characters = []
    for character in folded:
        category = unicodedata.category(character)
        if category in ("Pd", "Pc") or character in "/\\":
            characters.append(" ")
        elif not category.startswith("P"):
            characters.append(character)
    return " ".join("".join(characters).split())


def token_f1(pred: str, gold: str) -> float:
    """return the token-level F1 of two texts after normalisation; 1.0 when both are empty."""
    pred_tokens, gold_tokens = (
        Counter(normalise_text(pred).split()),
        Counter(normalise_text(gold).split()),
    )
    if not pred_tokens and not gold_tokens:
        return 1.0
    overlap = sum((pred_tokens & gold_tokens).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(pred_tokens.values())
    recall = overlap / sum(gold_tokens.values())
    return 2 * precision * recall / (precision + recall)


def parse_number(text: str) -> float | None:
    """return the first number written in text, in digits or English words; None if there is none.

    handles "1,234", "1.2k", "n = 120", "2.5e3", "-3.5" and "one hundred and twenty".
    decimal arithmetic avoids float artefacts such as 1.1k becoming 1100.0000000000002.
    """
    match = _NUMBER.search(text)
    if match is None:
        return _parse_number_words(text)
    return _number_value(match)


def numbers_in(text: str) -> list[float]:
    """return every number in text: each one in digits, in order, then the first in words."""
    numbers = [_number_value(match) for match in _NUMBER.finditer(text)]
    in_words = _parse_number_words(text)
    return numbers if in_words is None else [*numbers, in_words]


def contains_value(text: str, value: str, spec: FieldSpec, rules: MatchingSettings) -> bool:
    """return whether text, typically a quote from the paper, states value (spec 7.4).

    numeric: some number in text matches value within the field's tolerance. categorical:
    text contains the value or one of its synonyms as a phrase. short_text: text contains
    the value as a phrase. long_text: at least rules.long_text_min_f1 of the value's words
    occur in text, since a long answer paraphrases its source.
    """
    if spec.group == "numeric":
        return any(values_match(repr(number), value, spec, rules) for number in numbers_in(text))
    haystack = f" {normalise_text(text)} "
    if spec.group == "long_text":
        value_words = normalise_text(value).split()
        present = sum(f" {word} " in haystack for word in value_words)
        return bool(value_words) and present / len(value_words) >= rules.long_text_min_f1
    variants = [value, *(spec.synonyms or {}).get(value, ())]
    return any(
        normalise_text(variant) and f" {normalise_text(variant)} " in haystack
        for variant in variants
    )


def _number_value(match: re.Match[str]) -> float:
    value = Decimal(match["digits"].replace(",", ""))
    if match["exponent"]:
        value = value.scaleb(int(match["exponent"]))
    scale = match["suffix"] or match["word"]
    if scale:
        value *= _SCALES[scale.lower()]
    return float(-value if match["sign"] else value)


def _parse_number_words(text: str) -> float | None:
    # reads the first run of number words: "three thousand four hundred" -> 3400
    total = current = 0
    has_number = False
    for word in re.findall(r"[a-z]+", text.casefold()):
        if word in _UNIT_WORDS or word in _TENS_WORDS:
            current += _UNIT_WORDS.get(word, 0) + _TENS_WORDS.get(word, 0)
            has_number = True
        elif word == "hundred" and has_number:
            current *= 100
        elif word in ("thousand", "million", "billion") and has_number:
            total += current * _SCALES[word]
            current = 0
        elif word == "and" and has_number:
            continue
        elif has_number:
            break
    return float(total + current) if has_number else None


def values_match(a: str | None, b: str | None, spec: FieldSpec, rules: MatchingSettings) -> bool:
    """return whether a matches reference b under the rule for spec.group.

    numeric tolerances are relative to b. a number that cannot be parsed matches nothing.
    raises ConfigError only for contradictory synonyms in spec.
    """
    if a is None or b is None:
        return a is None and b is None
    if spec.group == "numeric":
        a_number, b_number = parse_number(a), parse_number(b)
        if a_number is None or b_number is None:
            return False
        tolerance = max(spec.numeric_tolerance, spec.rel_tolerance * abs(b_number))
        return abs(a_number - b_number) <= tolerance
    if spec.group == "long_text":
        return token_f1(a, b) >= rules.long_text_min_f1
    a_canonical, b_canonical = _canonical(a, spec), _canonical(b, spec)
    if spec.group == "categorical":
        return a_canonical == b_canonical
    return (
        a_canonical == b_canonical or token_f1(a_canonical, b_canonical) >= rules.short_text_min_f1
    )


def is_correct(
    pred: str | None, gold: str | None, spec: FieldSpec, rules: MatchingSettings
) -> bool:
    """return whether a predicted value is correct against the gold value (spec 6.4).

    raises ConfigError when the gold value itself is malformed: not a number for a numeric
    field, or not an allowed value for a categorical field.
    """
    if gold is not None and spec.group == "numeric" and parse_number(gold) is None:
        raise ConfigError(f"gold value {gold!r} for numeric field {spec.name} is not a number")
    if gold is not None and spec.group == "categorical" and allowed_value(gold, spec) is None:
        raise ConfigError(f"gold value {gold!r} is not allowed for field {spec.name}")
    return values_match(pred, gold, spec, rules)


def allowed_value(text: str, spec: FieldSpec) -> str | None:
    """return the allowed value that text names, spelt as in spec.allowed_values.

    text is compared after normalisation and synonym mapping, as in `values_match`. returns
    None when text names no allowed value, or when spec has no allowed values.
    """
    target = _canonical(text, spec)
    for value in spec.allowed_values or ():
        if _canonical(value, spec) == target:
            return value
    return None


def _canonical(text: str, spec: FieldSpec) -> str:
    normalised = normalise_text(text)
    return _synonym_lookup(spec).get(normalised, normalised)


def _synonym_lookup(spec: FieldSpec) -> dict[str, str]:
    # maps each normalised variant to its normalised canonical value
    lookup: dict[str, str] = {}
    for canonical, variants in (spec.synonyms or {}).items():
        target = normalise_text(canonical)
        for variant in (canonical, *variants):
            key = normalise_text(variant)
            if lookup.get(key, target) != target:
                raise ConfigError(
                    f"synonym {variant!r} of field {spec.name} maps to two values: "
                    f"{lookup[key]!r} and {target!r}"
                )
            lookup[key] = target
    return lookup
