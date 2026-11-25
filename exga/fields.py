"""reading and writing the user's field list, a YAML file (spec 6, 7.10).

the file holds one mapping with a `fields` list; each entry is a `FieldSpec`:

    fields:
      - name: sample_size
        description: total number of participants randomised
        group: numeric
"""

from collections.abc import Sequence
from pathlib import Path

import yaml
from pydantic import ValidationError

from exga.errors import ConfigError
from exga.schemas import FieldSpec


def parse_field(entry: object) -> FieldSpec:
    """one field spec from a mapping, such as a YAML entry or the app's form.

    raises ConfigError naming each problem, e.g. "name: String should match pattern ...".
    """
    try:
        return FieldSpec.model_validate(entry)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'entry'}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigError(problems) from exc


def load_fields(path: Path) -> tuple[FieldSpec, ...]:
    """return the field specs in the file at path, in file order.

    raises ConfigError naming the file and the offending entry when the file cannot be read,
    is not YAML of the expected shape, holds an invalid entry, or repeats a field name.
    """
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read field list {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"field list {path} is not valid YAML: {exc}") from exc
    if not isinstance(content, dict) or not isinstance(content.get("fields"), list):
        raise ConfigError(f"field list {path} must be a mapping with a 'fields' list")
    specs = []
    for index, entry in enumerate(content["fields"]):
        try:
            specs.append(parse_field(entry))
        except ConfigError as exc:
            raise ConfigError(f"field list {path}, fields[{index}]: {exc}") from exc
    names = [spec.name for spec in specs]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ConfigError(f"field list {path} repeats field names: {', '.join(repeated)}")
    if not specs:
        raise ConfigError(f"field list {path} has no fields")
    return tuple(specs)


def fields_to_yaml(specs: Sequence[FieldSpec]) -> str:
    """specs as the YAML text `load_fields` reads, leaving out default values."""
    entries = [spec.model_dump(mode="json", exclude_defaults=True) for spec in specs]
    return yaml.safe_dump({"fields": entries}, sort_keys=False, allow_unicode=True)


def save_fields(specs: Sequence[FieldSpec], path: Path) -> None:
    """write specs to path as `fields_to_yaml` text."""
    path.write_text(fields_to_yaml(specs), encoding="utf-8", newline="\n")
