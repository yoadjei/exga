"""a content-addressed disk cache in front of any `LLMClient` (spec 0, 0A.1, 7.2).

every request is keyed by everything that can change its answer: model, full prompt, n,
temperature, seed and JSON schema. a rerun of an experiment then sends no request it has sent
before, so it is cheap and returns the same completions. entries are plain JSON, one file per
request, so they can be inspected and deleted by hand.
"""

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path

from pydantic import TypeAdapter

from exga.errors import LLMResponseError
from exga.llm.base import LLMClient
from exga.schemas import RawResponse

_RESPONSES = TypeAdapter(tuple[RawResponse, ...])
# key prefix length used as a subfolder, so no folder holds more than a few thousand files
_SHARD_CHARS = 2
_DELETE_HINT = "delete it to refetch"


def cache_key(
    model_id: str,
    prompt: str,
    *,
    n: int,
    temperature: float,
    seed: int | None,
    json_schema: Mapping[str, object] | None,
) -> str:
    """return the sha256 hex digest identifying one request; JSON key order does not matter."""
    return hashlib.sha256(
        _canonical_json(_request(model_id, prompt, n, temperature, seed, json_schema))
    ).hexdigest()


class CachedLLMClient:
    """an `LLMClient` that answers repeated requests from files under root.

    a miss calls the inner client and writes the entry atomically (temporary file, then
    rename), so a crash never leaves a half-written entry and concurrent writers of the same
    key both leave a complete one. the hits and misses counters let a run report how many
    requests were actually sent.
    """

    def __init__(self, inner: LLMClient, root: Path) -> None:
        self._inner = inner
        self._root = root
        self._counter_lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @property
    def model_id(self) -> str:
        """identifier of the inner client's model."""
        return self._inner.model_id

    def generate(
        self,
        prompt: str,
        *,
        n: int,
        temperature: float,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> list[RawResponse]:
        """return the cached completions for this request, calling the inner client on a miss.

        raises LLMResponseError when an existing entry cannot be read or does not hold n
        responses; the entry is left in place for inspection.
        """
        key = cache_key(
            self.model_id, prompt, n=n, temperature=temperature, seed=seed, json_schema=json_schema
        )
        path = self._root / key[:_SHARD_CHARS] / f"{key}.json"
        hit = path.is_file()
        # worker threads share one client; += on an attribute is not atomic
        with self._counter_lock:
            if hit:
                self.hits += 1
            else:
                self.misses += 1
        if hit:
            return _read_entry(path, n)
        responses = self._inner.generate(
            prompt, n=n, temperature=temperature, json_schema=json_schema, seed=seed
        )
        request = _request(self.model_id, prompt, n, temperature, seed, json_schema)
        _write_entry(path, request, responses)
        return responses


def _request(
    model_id: str,
    prompt: str,
    n: int,
    temperature: float,
    seed: int | None,
    json_schema: Mapping[str, object] | None,
) -> dict[str, object]:
    return {
        "model_id": model_id,
        "prompt": prompt,
        "n": n,
        "temperature": temperature,
        "seed": seed,
        "json_schema": None if json_schema is None else dict(json_schema),
    }


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def _read_entry(path: Path, n: int) -> list[RawResponse]:
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
        responses = _RESPONSES.validate_python(content["responses"])
    # pydantic's ValidationError is a ValueError
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LLMResponseError(f"cache entry {path} is unreadable ({exc}); {_DELETE_HINT}") from exc
    if len(responses) != n:
        raise LLMResponseError(
            f"cache entry {path} holds {len(responses)} responses, expected {n}; {_DELETE_HINT}"
        )
    return list(responses)


def _write_entry(path: Path, request: dict[str, object], responses: list[RawResponse]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "request": request,
        "responses": [response.model_dump(mode="json") for response in responses],
    }
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(entry, handle, ensure_ascii=False, indent=1)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
