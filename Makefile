# developer and CI entry points. CI runs: make setup lint type test.
# on windows, install GNU make (winget install ezwinports.make) or run the commands directly.

UV ?= uv
# pure-core modules held to the 90% coverage floor (spec 0A.4); extended as each one lands
CORE_MODULES = exga/matching.py,exga/calibrate.py,exga/simulation.py,exga/document.py,exga/score.py,exga/decide.py,exga/labels.py,exga/messages.py,exga/splits.py

.PHONY: setup lint format type test verify-guarantee bench app experiments

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

# the targets below arrive with the phase that builds what they run (spec section 12)
app:
	@echo "make app: not available yet; arrives in phase P7 (web app)" >&2; exit 1

experiments:
	@echo "make experiments: not available yet; arrives in phase P8 (experiments)" >&2; exit 1
