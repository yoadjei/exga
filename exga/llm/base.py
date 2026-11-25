"""the interface every model back-end implements (spec 7.2).

a Protocol rather than a base class: back-ends satisfy it by shape, so the mock, hosted and
local clients share no code and need no inheritance.
"""

from collections.abc import Mapping
from typing import Protocol

from exga.schemas import RawResponse


class LLMClient(Protocol):
    """a model back-end that returns raw completions; parsing and validation happen elsewhere."""

    @property
    def model_id(self) -> str:
        """identifier of the model, stored with every extraction and part of every cache key."""

    def generate(
        self,
        prompt: str,
        *,
        n: int,
        temperature: float,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> list[RawResponse]:
        """return n completions of prompt sampled at temperature, in sample order.

        json_schema asks the back-end to constrain output to that JSON schema where it can;
        callers must still validate the text. seed is passed to back-ends that support
        seeded sampling and ignored by the rest. raises LLMResponseError when the back-end
        gives no usable response after retries.
        """
