"""asking the model about one item (paper, field) and reading its answers (spec 7.3).

for each chunk of a paper the model gives one greedy answer (temperature 0) and k sampled
answers. every reply is parsed and validated; a reply that fails gets one repair request, and
one that fails again counts as a failed sample. the paper text comes before the field in the
prompt, so providers that cache prompt prefixes reuse a paper across its fields. every word
the model reads, apart from the paper itself, lives in a versioned folder under prompts/.
"""

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import get_args

from exga.errors import ConfigError
from exga.matching import allowed_value, parse_number
from exga.schemas import (
    Chunk,
    FieldGroup,
    FieldSpec,
    RawResponse,
    SampleAnswer,
)

PROMPTS_ROOT = Path(__file__).parent / "prompts"

# main.txt tells the model that lines like this mark where each page starts
_PAGE_MARKER = "[page {}]"
# the "value" key of a JSON object, not the word inside a string (quotes there are escaped)
_VALUE_KEY = re.compile(r'(?:^|[{,])\s*"value"\s*:\s*')
_PARAGRAPH_BREAK = "\n\n"


class AnswerError(ValueError):
    """a reply that is not a usable answer; the message is shown to the model when repairing."""


@dataclass(frozen=True)
class Prompts:
    """one version of the prompt files, loaded with `load_prompts`."""

    version: str
    main: Template
    rules: Mapping[str, Template]
    numeric_unit: Template
    repair: Template


def load_prompts(version: str, root: Path = PROMPTS_ROOT) -> Prompts:
    """read the prompt files of one version; raises ConfigError when any is missing."""
    folder = root / version
    names = ["main", "numeric_unit", "repair", *get_args(FieldGroup)]
    missing = [name for name in names if not (folder / f"{name}.txt").is_file()]
    if missing:
        raise ConfigError(f"prompt version {version!r} in {root} lacks: {', '.join(missing)}")

    def read(name: str) -> Template:
        return Template((folder / f"{name}.txt").read_text(encoding="utf-8"))

    return Prompts(
        version=version,
        main=read("main"),
        rules={group: read(group) for group in get_args(FieldGroup)},
        numeric_unit=read("numeric_unit"),
        repair=read("repair"),
    )


def answer_schema(spec: FieldSpec) -> dict[str, object]:
    """the JSON schema of an answer, in the strict subset that providers can enforce."""
    value: dict[str, object] = {"type": ["string", "null"]}
    if spec.allowed_values is not None:
        value["enum"] = [*spec.allowed_values, None]
    return {
        "type": "object",
        "properties": {
            "value": value,
            "evidence": {"type": ["string", "null"]},
            "page": {"type": ["integer", "null"]},
        },
        "required": ["value", "evidence", "page"],
        "additionalProperties": False,
    }


def paper_text(part: Chunk) -> str:
    """the chunk's text with a page marker before the first paragraph of each page."""
    lines: list[str] = []
    page = None
    for paragraph, paragraph_page in zip(
        part.text.split(_PARAGRAPH_BREAK), part.paragraph_pages, strict=True
    ):
        if paragraph_page != page:
            lines.append(_PAGE_MARKER.format(paragraph_page))
            page = paragraph_page
        lines.append(paragraph)
    return _PARAGRAPH_BREAK.join(lines)


def build_prompt(prompts: Prompts, spec: FieldSpec, part: Chunk) -> str:
    """the extraction prompt for one field over one chunk."""
    unit_rule = prompts.numeric_unit.substitute(unit=spec.unit) if spec.unit else ""
    options = ", ".join(f'"{value}"' for value in spec.allowed_values or ())
    answer_rule = prompts.rules[spec.group].substitute(unit_rule=unit_rule, options=options)
    return prompts.main.substitute(
        paper_text=paper_text(part),
        field_name=spec.name,
        description=spec.description,
        answer_rule=answer_rule.strip(),
    )


def build_repair_prompt(prompts: Prompts, prompt: str, reply: str, problem: str) -> str:
    """the original prompt followed by the failed reply and what was wrong with it."""
    return prompt + "\n" + prompts.repair.substitute(problem=problem, reply=reply)


def read_answer(response: RawResponse, spec: FieldSpec) -> SampleAnswer:
    """parse and validate one reply; raises AnswerError saying what is wrong with it.

    accepts a JSON object, optionally inside a code fence or surrounded by prose. "value"
    must be present; a missing "evidence" or "page" counts as null, and a page that is not a
    positive integer is dropped, since it is only a hint. a categorical value is returned
    spelt as in spec.allowed_values.
    """
    answer = _json_object(response.text)
    if "value" not in answer:
        raise AnswerError('the reply has no "value" key')
    return SampleAnswer(
        value=_value(answer["value"], spec),
        evidence=_optional_text(answer.get("evidence"), "evidence"),
        page_hint=_page(answer.get("page")),
        mean_logprob=value_logprob(response),
    )


def value_logprob(response: RawResponse) -> float | None:
    """mean log-probability of the tokens that spell the answer's value (spec 7.4).

    None when the back-end gave no logprobs, when its tokens do not spell the reply text
    exactly, or when the reply has no "value" key.
    """
    tokens = response.token_logprobs
    if tokens is None or "".join(token.token for token in tokens) != response.text:
        return None
    span = _value_span(response.text)
    if span is None:
        return None
    start, end = span
    selected = []
    offset = 0
    for token in tokens:
        token_end = offset + len(token.token)
        if offset < end and token_end > start:
            selected.append(token.logprob)
        offset = token_end
    return math.fsum(selected) / len(selected) if selected else None


def _json_object(text: str) -> dict[str, object]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise AnswerError("the reply contains no JSON object")
    try:
        answer = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AnswerError(f"the reply is not valid JSON ({exc.msg})") from exc
    if not isinstance(answer, dict):
        raise AnswerError("the reply is not a JSON object")
    return answer


def _value(raw: object, spec: FieldSpec) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, str | int | float):
        raise AnswerError('"value" must be a string, a number or null')
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    value = str(raw).strip()
    if not value:
        return None
    if spec.group == "categorical":
        option = allowed_value(value, spec)
        if option is None:
            options = ", ".join(f'"{option}"' for option in spec.allowed_values or ())
            raise AnswerError(f'"value" must be one of {options}, or null')
        return option
    if spec.group == "numeric" and parse_number(value) is None:
        raise AnswerError('"value" must be a number, or null if the paper does not report it')
    return value


def _optional_text(raw: object, key: str) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise AnswerError(f'"{key}" must be a string or null')
    return raw.strip() or None


def _page(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 1 else None
    if isinstance(raw, str) and raw.strip().isdigit():
        return _page(int(raw))
    return None


def _value_span(text: str) -> tuple[int, int] | None:
    key = _VALUE_KEY.search(text)
    if key is None:
        return None
    start = key.end()
    try:
        value, end = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return None
    # the characters of a string value, without its quotes; an empty string keeps them
    if isinstance(value, str) and value:
        return start + 1, end - 1
    return start, end
