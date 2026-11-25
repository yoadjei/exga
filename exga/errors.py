"""errors exga raises on purpose; catching `ExgaError` covers all of them.

each subclass names one failure mode the caller can recover from. anything else is a bug
and should propagate unchanged.
"""


class ExgaError(Exception):
    """base class for every error exga raises on purpose."""


class ConfigError(ExgaError):
    """settings, field specs or experiment configs are missing or invalid."""


class PdfParseError(ExgaError):
    """a PDF cannot be opened or yields no usable text, for example a scanned document."""


class LLMResponseError(ExgaError):
    """a model back-end gave no usable response after any retries and the one repair attempt."""


class BudgetExceededError(ExgaError):
    """a run has spent its configured model budget; no further requests are sent."""


class InsufficientCalibrationError(ExgaError):
    """a calibration unit has too few records to attempt certification at all.

    distinct from a NOT_CERTIFIABLE result, which is a normal outcome of certification.
    """
