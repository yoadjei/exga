# exga documentation

## Using exga

- [README](../README.md): what exga does, installation, starting the app, the command line
- [User guide](user_guide.md): the app page by page, settings, troubleshooting
- [Method](method.md): what is certified, under which assumptions, and why it holds
- [Limitations](limitations.md): what exga cannot do or promises only under conditions

## Reproducing the results

- **Guarantee and audit simulations:** `make verify-guarantee` writes
  `results/guarantee_simulation.csv` and `results/audit_simulation.csv` (ADRs 0004, 0009).
- **Experiments** (spec 11.1): configs in `experiments/` for the benchmark
  (`main.yaml`, `ablations.yaml`) and the owner's annotated set (`annotated.yaml`);
  `make experiments` writes tables, figures, records files and a manifest per config to
  `results/` (ADR 0011). The benchmark is downloaded by `scripts/download_benchmark.py`; the
  annotated set is built as described in [data/annotated/README.md](../data/annotated/README.md).
- **User study** (spec 11.3): [study/README.md](../study/README.md) and ADR 0012.
- **Install check:** `make install-check` installs the wheel into a clean environment and
  starts the app from it.

## Design and progress

- [Decision records](adr/): one per decision, with the alternatives and reasons
- [Progress](PROGRESS.md): phase status, test status, findings and the owner's next actions
- [Build specification](PROJECT_BUILD_SPEC.md): the brief exga was built to
