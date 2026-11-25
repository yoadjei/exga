# developer and CI entry points. CI runs: make setup lint type test.
# on windows, install GNU make (winget install ezwinports.make) or run the commands directly.

UV ?= uv

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

# fast test suite with a coverage report
test:
	$(UV) run pytest --cov --cov-report=term-missing

# the targets below arrive with the phase that builds what they run (spec section 12)
verify-guarantee bench:
	@echo "make $@: not available yet; arrives in phase P1 (calibration core)" >&2; exit 1

app:
	@echo "make app: not available yet; arrives in phase P7 (web app)" >&2; exit 1

experiments:
	@echo "make experiments: not available yet; arrives in phase P8 (experiments)" >&2; exit 1
