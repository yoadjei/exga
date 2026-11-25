# developer and CI entry points. CI runs: make setup lint type test.
# on windows, install GNU make (winget install ezwinports.make) or run the commands directly.

UV ?= uv
# pure-core modules held to the 90% coverage floor (spec 0A.4); extended as each one lands
CORE_MODULES = exga/matching.py,exga/calibrate.py,exga/simulation.py,exga/document.py,exga/score.py,exga/decide.py,exga/labels.py,exga/messages.py,exga/splits.py,exga/audit.py,exga/views.py,exga/evaluate.py

.PHONY: setup lint format type test verify-guarantee bench app experiments install-check thesis

# create .venv with the exact versions pinned in uv.lock, including dev tools
setup:
	$(UV) sync --locked

# lint and check formatting without changing any file
lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

# apply formatting and safe lint fixes
format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

# strict type check of the library and tests (paths configured in pyproject.toml)
type:
	$(UV) run mypy

# fast test suite with a coverage report, then the coverage floor on the pure core
test:
	$(UV) run pytest --cov --cov-report=term-missing
	$(UV) run coverage report --include="$(CORE_MODULES)" --fail-under=90

# full 1,000-repetition guarantee simulation; writes results/guarantee_simulation.csv
verify-guarantee:
	$(UV) run python scripts/verify_guarantee.py
	$(UV) run python scripts/verify_audit.py

# core-path timing against the budget in spec 0A.5
bench:
	$(UV) run python scripts/bench.py

# build the wheel, install it into a fresh environment with an empty home folder, and run
# the CLI and the app from it (P10)
install-check:
	UV="$(UV)" $(UV) run python scripts/check_install.py

# the web app on http://localhost:8501, reachable from this computer only (ADR 0010)
app:
	$(UV) run exga app

# the spec 11.1 experiments (ADR 0011): extract, then tables, figures and a manifest under
# results/. extraction sends paid requests unless they are cached; set the model ids in the
# configs, the key and a budget first (see experiments/main.yaml)
experiments:
	$(UV) run python experiments/run.py extract experiments/main.yaml
	$(UV) run python experiments/run.py evaluate experiments/main.yaml
	$(UV) run python experiments/run.py extract experiments/ablations.yaml
	$(UV) run python experiments/run.py evaluate experiments/ablations.yaml
	$(UV) run python experiments/run.py extract experiments/annotated.yaml
	$(UV) run python experiments/run.py evaluate experiments/annotated.yaml

# the thesis tables (LaTeX and CSV) and figures (PDF and PNG) under results/thesis/, from
# every result that exists; missing ones are named, never filled in (ADR 0013)
thesis:
	$(UV) run python experiments/thesis.py
