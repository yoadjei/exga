"""a deterministic `LLMClient` for tests and offline runs; it never touches the network."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from exga.schemas import RawResponse, TokenLogprob


@dataclass(frozen=True)
class MockCall:
    """the arguments of one `generate` call, kept so tests can assert how the client was used."""

    prompt: str
    n: int
    temperature: float
    json_schema: Mapping[str, object] | None
    seed: int | None


# maps a call and a 0-based sample index to the completion text for that sample
Reply = Callable[[MockCall, int], str]


class MockLLMClient:
    """replays completions from a reply function instead of calling a model.

    token counts are whitespace word counts, a stand-in for a real tokenizer. when
    token_logprob is set, every whitespace token gets that log-probability, which is enough
    to exercise the logprob signal; otherwise logprobs are absent, as with back-ends that do
    not expose them.
    """

    def __init__(
        self, reply: Reply, *, model_id: str = "mock", token_logprob: float | None = None
    ) -> None:
        if token_logprob is not None and token_logprob > 0:
            raise ValueError(f"token_logprob must be <= 0, got {token_logprob}")
        self._reply = reply
        self._model_id = model_id
        self._token_logprob = token_logprob
        self.calls: list[MockCall] = []

    @property
    def model_id(self) -> str:
        """identifier reported for extractions made with this client."""
        return self._model_id

    def generate(
        self,
        prompt: str,
        *,
        n: int,
        temperature: float,
        json_schema: Mapping[str, object] | None = None,
        seed: int | None = None,
    ) -> list[RawResponse]:
        """return n replies to prompt and record the call; raises ValueError when n < 1."""
        if n < 1:
            raise ValueError(f"n must be at least 1, got {n}")
        call = MockCall(
            prompt=prompt, n=n, temperature=temperature, json_schema=json_schema, seed=seed
        )
        self.calls.append(call)
        return [self._respond(call, sample_index) for sample_index in range(n)]

    def _respond(self, call: MockCall, sample_index: int) -> RawResponse:
        text = self._reply(call, sample_index)
        words = text.split()
        logprobs = (
            None
            if self._token_logprob is None
            else tuple(TokenLogprob(token=word, logprob=self._token_logprob) for word in words)
        )
        return RawResponse(
            text=text,
            token_logprobs=logprobs,
            input_tokens=len(call.prompt.split()),
            output_tokens=len(words),
        )
