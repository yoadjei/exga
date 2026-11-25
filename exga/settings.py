"""runtime configuration: every tunable number in exga is a named, documented setting here.

values come from defaults, then an optional env file, then ``EXGA_`` environment variables,
which win. nested groups use a double underscore, e.g. ``EXGA_CALIBRATION__ALPHA=0.1``.
the shell builds one `Settings` with `load_settings` and passes it down explicitly; no module
reads settings from global state.

a settings group is added in the phase that first uses it, so nothing here is speculative.
"""

import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
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
    """m_min: grid thresholds accepting fewer calibration items than this are skipped."""

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
