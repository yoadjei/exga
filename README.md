# exga

exga extracts user-defined fields, such as sample sizes or event counts, from research-paper
PDFs with a large language model. It scores how confident it is in each value and accepts a
value only when that score clears a threshold certified on human-checked values. For each
field, the error rate among accepted values is then at most a chosen α (5% by default), with
probability at least 1 − δ (90% by default). Every other value is marked for a person to
check, with the passage of the paper it came from highlighted.

exga is a Python library, a command line, and a web app that runs on your own computer.

**Status: 0.1.0.** The method, the app and the experiment and user-study pipelines are built
and tested; the guarantee is verified by simulation (`results/guarantee_simulation.csv`).
Measurements with real models and the user study have not been run yet, so no accuracy or
time saving is claimed here. Details: [docs/PROGRESS.md](docs/PROGRESS.md).

## What is promised, and what is not

For **each field separately**, with probability at least 1 − δ over the checked values used
for calibration, the share of wrong values among the values exga accepts is at most α. This
holds when:

- the checked values come from papers like the ones being processed (exchangeability);
- they are a random sample of extracted values: exga's random audits ensure this, values
  someone chose to check do not;
- each paper contributes at most one checked value per field.

It does **not** promise that all fields are right at once, that a field can be certified at
all (a field needs enough checked values: at α = 5%, at least 45 accepted ones without an
error), or anything for scanned PDFs, which have no text layer and are not read. The full
statement and proof: [docs/method.md](docs/method.md). Everything known to limit it:
[docs/limitations.md](docs/limitations.md).

## Install

Python 3.11 or newer. exga is not on PyPI; install it from GitHub into a virtual environment:

```
python -m venv .venv
.venv\Scripts\activate          (Windows)
source .venv/bin/activate       (macOS, Linux)
pip install "exga @ git+https://github.com/yoadjei/exga@v0.1.0"
```

## Start the app

exga needs a model endpoint that speaks the OpenAI chat-completions API **and returns token
log-probabilities**, which one of its confidence signals uses. A hosted provider and a local
vLLM or llama.cpp server both work ([ADR 0006](docs/adr/0006-model-back-ends.md)). Put the
settings in a file called `.env`:

```
EXGA_HOSTED__BASE_URL=https://api.openai.com/v1
EXGA_HOSTED__MODEL=<model name>
EXGA_HOSTED__API_KEY=<your key>
EXGA_HOSTED__INPUT_PRICE_PER_MILLION=<USD per million prompt tokens>
EXGA_HOSTED__OUTPUT_PRICE_PER_MILLION=<USD per million completion tokens>
EXGA_HOSTED__BUDGET_USD=5
```

The prices and budget are optional; with them, exga stops a run once it has spent the budget.
Keep `.env` out of version control. Then:

```
exga app --env-file .env
```

The app opens in your browser at http://localhost:8501 and is reachable from this computer
only. Paper text is sent to the model endpoint you configure, and nowhere else; the app asks
for your consent before it sends anything to an endpoint that is not on this computer. The
pages follow the work: **Project → Fields → Upload and run → Calibrate → Review → Audit →
Export**. The [user guide](docs/user_guide.md) walks through them.

## Command line

```
exga extract --papers <folder> --fields <fields.yaml> --out <folder> --env-file .env
exga annotation-sheet --papers <folder> --fields <fields.yaml> --out <folder>
exga check-gold --gold gold.csv --fields <fields.yaml>
exga app --env-file .env
```

`extract` writes every answer to `samples.jsonl` and a summary with costs to `run.json`.
`annotation-sheet` and `check-gold` prepare and validate human-checked values. `exga <command>
--help` lists every option. [examples/fields.yaml](examples/fields.yaml) is a field list to
start from.

## Documentation

- [docs/user_guide.md](docs/user_guide.md): the app page by page, settings, troubleshooting
- [docs/method.md](docs/method.md): what is certified, under which assumptions, and why
- [docs/limitations.md](docs/limitations.md): known limits
- [docs/adr/](docs/adr/): every design decision with its reasons
- [docs/index.md](docs/index.md): everything else, including experiments and the user study

## Development

Requires [uv](https://docs.astral.sh/uv/) and GNU make. On Windows, install make with
`winget install ezwinports.make`, or run the commands listed in the `Makefile` directly.

```
make setup              # .venv with Python 3.11 and the versions pinned in uv.lock
make lint               # ruff check and format check
make type               # mypy --strict
make test               # pytest with coverage
make verify-guarantee   # the 1,000-repetition guarantee and audit simulations
make bench              # core timings against the budget
make install-check      # build the wheel, install it in a clean environment, start the app
make experiments        # the experiments from experiments/*.yaml (sends paid requests)
```

## Citing

If you use exga, please cite it as described in [CITATION.cff](CITATION.cff).

## Licence

exga's own code is MIT; see [LICENSE](LICENSE).

exga depends on [PyMuPDF](https://pymupdf.readthedocs.io/), which is licensed under the
AGPL-3.0 (or a commercial licence from Artifex). Anyone who distributes exga together with
PyMuPDF, or runs a modified version as a network service, must meet the AGPL's terms.
