# exga

exga is a Python library and web app being built to extract user-defined fields from
research-paper PDFs with a large language model, score each value's confidence, and accept a
value only when it clears a threshold certified on human-checked data, so that the error rate
among accepted values is at most a chosen α with probability at least 1 − δ. Values below the
threshold are flagged for a person to check.

**Status:** early development, phase P0 (project setup). Nothing is usable yet. Current state:
[docs/PROGRESS.md](docs/PROGRESS.md).

## Development

Requires [uv](https://docs.astral.sh/uv/) and GNU make. On Windows, install make with
`winget install ezwinports.make`, or run the commands listed in the `Makefile` directly.

```
make setup   # create .venv with Python 3.11 and the dev tools pinned in uv.lock
make lint    # ruff check and format check
make type    # mypy --strict
make test    # pytest with coverage
```

Specification: [docs/PROJECT_BUILD_SPEC.md](docs/PROJECT_BUILD_SPEC.md).
Design decisions: [docs/adr/](docs/adr/).

## Licence

MIT; see [LICENSE](LICENSE).
