import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from exga.errors import ConfigError
from exga.settings import CalibrationSettings, load_settings


@pytest.fixture(autouse=True)
def _isolate_from_developer_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [name for name in os.environ if name.upper().startswith("EXGA_")]:
        monkeypatch.delenv(name)


def test_defaults_match_the_specification() -> None:
    calibration = load_settings().calibration

    assert calibration.alpha == 0.05
    assert calibration.delta == 0.1
    assert calibration.min_accepted == 10
    assert calibration.grid_step == 0.005


def test_environment_variable_overrides_a_nested_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXGA_CALIBRATION__ALPHA", "0.1")

    assert load_settings().calibration.alpha == 0.1


def test_env_file_values_are_read(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EXGA_CALIBRATION__DELTA=0.2\n")

    assert load_settings(env_file).calibration.delta == 0.2


def test_environment_variable_takes_precedence_over_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EXGA_CALIBRATION__DELTA=0.2\n")
    monkeypatch.setenv("EXGA_CALIBRATION__DELTA", "0.05")

    assert load_settings(env_file).calibration.delta == 0.05


@pytest.mark.parametrize("bad_alpha", ["0", "1", "1.5", "-0.1", "five percent"])
def test_invalid_value_raises_config_error_naming_the_setting(
    monkeypatch: pytest.MonkeyPatch, bad_alpha: str
) -> None:
    monkeypatch.setenv("EXGA_CALIBRATION__ALPHA", bad_alpha)

    with pytest.raises(ConfigError, match=r"calibration\.alpha"):
        load_settings()


def test_misspelt_setting_in_env_file_is_rejected(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("EXGA_CALIBRATION__ALPA=0.1\n")

    with pytest.raises(ConfigError, match="alpa"):
        load_settings(env_file)


def test_missing_env_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "missing.env")


@pytest.mark.parametrize("step", [0.005, 0.01, 0.25, 1.0])
def test_grid_steps_that_divide_the_unit_interval_are_accepted(step: float) -> None:
    assert CalibrationSettings(grid_step=step).grid_step == step


@pytest.mark.parametrize("step", [0.3, 0.007, 0.0, 1.5])
def test_grid_steps_that_cannot_reach_both_ends_are_rejected(step: float) -> None:
    with pytest.raises(ValidationError, match="grid_step"):
        CalibrationSettings(grid_step=step)


def test_settings_cannot_be_changed_after_loading() -> None:
    settings = load_settings()

    with pytest.raises(ValidationError, match="frozen"):
        settings.calibration.alpha = 0.2  # type: ignore[misc]


def test_the_api_key_is_read_from_the_environment_but_never_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXGA_HOSTED__API_KEY", "sk-test-secret")

    hosted = load_settings().hosted

    assert hosted.api_key is not None
    assert hosted.api_key.get_secret_value() == "sk-test-secret"
    assert "sk-test-secret" not in repr(hosted)


def test_a_budget_without_token_prices_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXGA_HOSTED__BUDGET_USD", "5")

    with pytest.raises(ConfigError, match="budget_usd needs"):
        load_settings()


def test_a_priced_budget_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXGA_HOSTED__BUDGET_USD", "5")
    monkeypatch.setenv("EXGA_HOSTED__INPUT_PRICE_PER_MILLION", "0.15")
    monkeypatch.setenv("EXGA_HOSTED__OUTPUT_PRICE_PER_MILLION", "0.6")

    assert load_settings().hosted.budget_usd == 5.0
