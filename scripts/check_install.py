"""check that exga installs from its wheel into a clean environment and starts (spec 12, P10).

builds the wheel, installs it into a new virtual environment in a temporary folder, and then,
using only that environment and an empty home folder (a person who never ran exga or
Streamlit):

1. every file of the exga package in git is inside the installed package;
2. `exga --help` runs;
3. the app's first page runs from the installed package without an error;
4. `exga app` starts and answers on its health endpoint, with no prompt in the way.

the temporary folder is removed afterwards. exits with 1 if a check fails.
run with: make install-check (uv must be on PATH, or named by the UV environment variable)
"""

import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
PYTHON = "3.11"
"""the oldest Python exga supports (requires-python)."""
START_TIMEOUT = 90.0
"""seconds to wait for the app server to report its address and answer."""
WINDOWS = sys.platform == "win32"
if sys.platform == "win32":
    NEW_PROCESS_GROUP = subprocess.CREATE_NEW_PROCESS_GROUP
else:
    NEW_PROCESS_GROUP = 0
_URL = re.compile(r"http://localhost:(\d+)")
_FIRST_PAGE = """
import sys
from importlib.resources import files
from streamlit.testing.v1 import AppTest

app = AppTest.from_file(str(files("exga") / "app" / "main.py"), default_timeout=60).run()
if app.exception:
    sys.exit(f"the first page raised: {app.exception[0].message}")
print(app.title[0].value)
"""


def main() -> int:
    """build, install and run every check; 0 when all pass, else 1."""
    uv = os.environ.get("UV", "uv")
    if shutil.which(uv) is None:
        print(f"uv not found as {uv!r}; put it on PATH or set UV", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="exga-install-", ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        home = root / "home"
        home.mkdir()
        environment = _clean_environment(home)
        try:
            _run([uv, "build", "--wheel", "--out-dir", str(root / "dist")], cwd=REPOSITORY)
            [wheel] = (root / "dist").glob("exga-*.whl")
            _run([uv, "venv", str(root / "venv"), "--python", PYTHON])
            python = _executable(root / "venv", "python")
            _run([uv, "pip", "install", "--python", str(python), str(wheel)])
            checks: list[tuple[str, Callable[[], str | None]]] = [
                ("package files", lambda: _package_files(python, environment)),
                ("exga --help", lambda: _help(root / "venv", environment)),
                ("first page", lambda: _first_page(python, environment)),
                ("exga app", lambda: _serves(root / "venv", environment)),
            ]
        except subprocess.CalledProcessError as exc:
            print(f"FAILED to build or install: {exc}\n{exc.stdout}{exc.stderr}", file=sys.stderr)
            return 1
        failures = 0
        for name, check in checks:
            problem = check()
            print(f"ok  {name}" if problem is None else f"FAILED  {name}: {problem}")
            failures += problem is not None
    print(f"installed from {wheel.name} with Python {PYTHON}")
    return 1 if failures else 0


def _clean_environment(home: Path) -> dict[str, str]:
    """this process's environment without exga settings and with an empty home folder."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("EXGA_")}
    environment |= {"HOME": str(home), "USERPROFILE": str(home), "PYTHONIOENCODING": "utf-8"}
    return environment


def _package_files(python: Path, environment: dict[str, str]) -> str | None:
    installed = Path(
        _run(
            [str(python), "-c", "import exga, pathlib; print(pathlib.Path(exga.__file__).parent)"],
            env=environment,
        ).strip()
    )
    tracked = _run(["git", "ls-files", "exga"], cwd=REPOSITORY).split()
    missing = [name for name in tracked if not (installed.parent / name).is_file()]
    return f"not in the wheel: {', '.join(missing)}" if missing else None


def _help(venv: Path, environment: dict[str, str]) -> str | None:
    result = subprocess.run(
        [str(_executable(venv, "exga")), "--help"],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0 or "app" not in result.stdout:
        return f"exit {result.returncode}: {result.stderr.strip()}"
    return None


def _first_page(python: Path, environment: dict[str, str]) -> str | None:
    result = subprocess.run(
        [str(python), "-c", _FIRST_PAGE],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return None if result.returncode == 0 else (result.stderr.strip() or result.stdout.strip())


def _serves(venv: Path, environment: dict[str, str]) -> str | None:
    """start `exga app`, read the address it prints and wait for its health endpoint."""
    process = subprocess.Popen(
        [str(_executable(venv, "exga")), "app"],
        env=environment | {"BROWSER": "none"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        # its own process group, so stopping it stops the Streamlit server it starts too
        creationflags=NEW_PROCESS_GROUP,
        start_new_session=not WINDOWS,
    )
    lines: queue.Queue[str] = queue.Queue()
    output: list[str] = []
    threading.Thread(target=_pump, args=(process, lines), daemon=True).start()
    try:
        deadline = time.monotonic() + START_TIMEOUT
        port = None
        while port is None and time.monotonic() < deadline:
            if process.poll() is not None and lines.empty():
                return f"exited with {process.returncode}: {''.join(output).strip()}"
            try:
                line = lines.get(timeout=1.0)
            except queue.Empty:
                continue
            output.append(line)
            match = _URL.search(line)
            port = match.group(1) if match else None
        if port is None:
            return f"printed no address within {START_TIMEOUT:.0f} s: {''.join(output).strip()}"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://localhost:{port}/_stcore/health", timeout=5
                ) as r:
                    if r.read().decode() == "ok":
                        return None
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                time.sleep(1.0)
        return f"no answer on port {port} within {START_TIMEOUT:.0f} s"
    finally:
        _stop(process)


def _pump(process: subprocess.Popen[str], lines: queue.Queue[str]) -> None:
    """copy the server's output into lines, so the main thread can wait with a timeout."""
    if process.stdout is not None:
        for line in process.stdout:
            lines.put(line)


def _stop(process: subprocess.Popen[str]) -> None:
    """stop `exga app` and the Streamlit server it started."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True, check=False
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    process.wait(timeout=30)


def _executable(venv: Path, name: str) -> Path:
    return venv / ("Scripts" if WINDOWS else "bin") / (f"{name}.exe" if WINDOWS else name)


def _run(args: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        args, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


if __name__ == "__main__":
    sys.exit(main())
