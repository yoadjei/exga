import pytest

from exga.errors import ConfigError
from exga.matching import (
    allowed_value,
    is_correct,
    normalise_text,
    parse_number,
    token_f1,
    values_match,
)
from exga.schemas import FieldSpec
from exga.settings import MatchingSettings

RULES = MatchingSettings()

SAMPLE_SIZE = FieldSpec(name="sample_size", description="participants randomised", group="numeric")
DESIGN = FieldSpec(
    name="study_design",
    description="design of the study",
    group="categorical",
    allowed_values=("rct", "cohort", "case_control"),
    synonyms={
        "rct": ("randomised controlled trial", "randomized controlled trial"),
        "case_control": ("case-control study",),
    },
)
COUNTRY = FieldSpec(
    name="country",
    description="country where data were collected",
    group="short_text",
    synonyms={"united states": ("usa", "us")},
)
RESULT = FieldSpec(name="primary_result", description="main finding", group="long_text")


def numeric(abs_tol: float = 0.0, rel_tol: float = 0.0) -> FieldSpec:
    return FieldSpec(
        name="mean_age",
        description="mean age in years",
        group="numeric",
        numeric_tolerance=abs_tol,
        rel_tolerance=rel_tol,
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("120", 120),
        ("1,234", 1234),
        ("1,234.5", 1234.5),
        ("1.2k", 1200),
        ("1.1k", 1100),
        ("n = 120", 120),
        ("N=120", 120),
        ("120 participants (60 per arm)", 120),
        ("-3.5", -3.5),
        ("\u22123.5", -3.5),
        (".5", 0.5),
        ("2.5e3", 2500),
        ("45%", 45),
        ("12 thousand", 12_000),
        ("1.5 million", 1_500_000),
        ("one hundred and twenty", 120),
        ("twenty-five", 25),
        ("Sixty-two patients", 62),
        ("three thousand four hundred", 3400),
        ("twelve hundred", 1200),
        ("COVID-19", 19),
    ],
)
def test_parse_number_reads_the_first_number_in_common_formats(text: str, expected: float) -> None:
    assert parse_number(text) == expected


@pytest.mark.parametrize("text", ["", "not reported", "NR", "several"])
def test_parse_number_returns_none_when_there_is_no_number(text: str) -> None:
    assert parse_number(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("  Case-Control  Study. ", "case control study"),
        ("case_control", "case control"),
        ("U.S.A.", "usa"),
        ("Ghana/Togo", "ghana togo"),
    ],
)
def test_normalise_text_folds_case_punctuation_and_spaces(text: str, expected: str) -> None:
    assert normalise_text(text) == expected


def test_token_f1_scores_overlap_symmetrically() -> None:
    assert token_f1("the quick fox", "quick brown fox") == pytest.approx(2 / 3)
    assert token_f1("quick brown fox", "the quick fox") == pytest.approx(2 / 3)
    assert token_f1("same words", "Same, words!") == 1.0
    assert token_f1("ghana", "nigeria") == 0.0
    assert token_f1("", "") == 1.0


@pytest.mark.parametrize("spec", [SAMPLE_SIZE, DESIGN, COUNTRY, RESULT], ids=lambda s: s.group)
def test_not_reported_matches_only_not_reported(spec: FieldSpec) -> None:
    gold = {"numeric": "120", "categorical": "rct", "short_text": "ghana", "long_text": "x"}
    value = gold[spec.group]

    assert is_correct(None, None, spec, RULES)
    assert not is_correct(None, value, spec, RULES)
    assert not is_correct(value, None, spec, RULES)


@pytest.mark.parametrize(
    ("pred", "gold", "spec", "expected"),
    [
        ("120", "120.0", SAMPLE_SIZE, True),
        ("n = 120", "120", SAMPLE_SIZE, True),
        ("one hundred and twenty", "120", SAMPLE_SIZE, True),
        ("121", "120", SAMPLE_SIZE, False),
        ("about a hundred", "120", SAMPLE_SIZE, False),
        ("41", "40", numeric(abs_tol=1.0), True),
        ("42", "40", numeric(abs_tol=1.0), False),
        ("1009", "1000", numeric(rel_tol=0.01), True),
        ("1011", "1000", numeric(rel_tol=0.01), False),
        ("1011", "1000", numeric(abs_tol=20.0, rel_tol=0.01), True),
    ],
)
def test_numeric_values_match_within_the_larger_tolerance(
    pred: str, gold: str, spec: FieldSpec, expected: bool
) -> None:
    assert is_correct(pred, gold, spec, RULES) is expected


def test_unparsable_numeric_gold_is_a_labelling_error() -> None:
    with pytest.raises(ConfigError, match="sample_size"):
        is_correct("120", "unclear", SAMPLE_SIZE, RULES)


def test_values_match_treats_an_unparsable_number_as_a_mismatch() -> None:
    # agreement between two model samples must never raise, whatever the model wrote
    assert not values_match("120", "lots", SAMPLE_SIZE, RULES)


@pytest.mark.parametrize(
    ("pred", "expected"),
    [
        ("RCT ", True),
        ("Randomized Controlled Trial", True),
        ("case-control study", True),
        ("case control", True),
        ("cohort", False),
        ("randomised trial", False),
    ],
)
def test_categorical_values_match_after_normalising_and_synonyms(pred: str, expected: bool) -> None:
    gold = "case_control" if "case" in pred else "rct"

    assert is_correct(pred, gold, DESIGN, RULES) is expected


def test_categorical_gold_outside_the_allowed_values_is_a_labelling_error() -> None:
    with pytest.raises(ConfigError, match="study_design"):
        is_correct("rct", "cross-sectional", DESIGN, RULES)


def test_synonyms_that_normalise_to_two_canonical_values_are_rejected() -> None:
    clash = DESIGN.model_copy(update={"synonyms": {"rct": ("trial",), "cohort": ("Trial.",)}})

    with pytest.raises(ConfigError, match="maps to two values"):
        is_correct("rct", "rct", clash, RULES)


@pytest.mark.parametrize(
    ("pred", "gold", "expected"),
    [
        ("Ghana.", "ghana", True),
        ("the United Kingdom", "United Kingdom", True),
        ("USA", "United States", True),
        ("Ghana", "Nigeria", False),
        ("United Kingdom and Ireland", "United Kingdom", False),
    ],
)
def test_short_text_matches_exactly_or_with_high_token_overlap(
    pred: str, gold: str, expected: bool
) -> None:
    assert is_correct(pred, gold, COUNTRY, RULES) is expected


@pytest.mark.parametrize(
    ("pred", "expected"),
    [
        ("depression scores fell more with the intervention than with usual care", True),
        ("the intervention reduced depression scores compared with usual care", True),
        ("no difference in anxiety", False),
    ],
)
def test_long_text_matches_with_moderate_token_overlap(pred: str, expected: bool) -> None:
    gold = "the intervention reduced depression scores more than usual care"

    assert is_correct(pred, gold, RESULT, RULES) is expected


def test_thresholds_come_from_settings() -> None:
    strict = MatchingSettings(short_text_min_f1=1.0)

    assert is_correct("the United Kingdom", "United Kingdom", COUNTRY, RULES)
    assert not is_correct("the United Kingdom", "United Kingdom", COUNTRY, strict)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("rct", "rct"),
        ("RCT", "rct"),
        ("Randomized Controlled Trial", "rct"),
        ("case-control study", "case_control"),
        ("case control", "case_control"),
        ("cross-sectional", None),
    ],
)
def test_allowed_value_names_the_option_a_text_refers_to(text: str, expected: str | None) -> None:
    assert allowed_value(text, DESIGN) == expected


def test_allowed_value_is_none_for_fields_without_options() -> None:
    assert allowed_value("usa", COUNTRY) is None
