import pytest

from exga.errors import (
    ConfigError,
    ExgaError,
    InsufficientCalibrationError,
    LLMResponseError,
    PdfParseError,
)


@pytest.mark.parametrize(
    "error_type",
    [ConfigError, PdfParseError, LLMResponseError, InsufficientCalibrationError],
)
def test_callers_can_catch_every_specific_error_through_the_base_class(
    error_type: type[ExgaError],
) -> None:
    with pytest.raises(ExgaError, match="paper_id=abc"):
        raise error_type("paper_id=abc")
