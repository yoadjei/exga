"""download the Yun et al. (2024) benchmark at its pinned commit into data/benchmark/raw/.

usage: uv run python scripts/download_benchmark.py

the data are Apache-2.0 (ADR 0008) but are not committed here (spec 10.1). the annotation
file must match its recorded sha256; every downloaded file's hash goes into MANIFEST.json, so
a run can show which data it used. files already present are not downloaded again.
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

from exga.benchmark import (
    ANNOTATIONS_PATH,
    ANNOTATIONS_SHA256,
    SOURCE_COMMIT,
    SOURCE_REPOSITORY,
    TEXT_FOLDER,
    read_annotations,
)

RAW = Path(__file__).parents[1] / "data" / "benchmark" / "raw"
BASE_URL = f"https://raw.githubusercontent.com/hyesunyun/llm-meta-analysis/{SOURCE_COMMIT}"
ATTEMPTS = 3
TIMEOUT_S = 60.0


def _fetch(client: httpx.Client, url: str, path: Path) -> None:
    if path.is_file():
        return
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            if attempt == ATTEMPTS:
                raise
            print(f"  retrying {path.name} after {exc}")
            time.sleep(2.0 * attempt)
            continue
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(response.content)
        temporary.replace(path)
        return


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    """download what is missing, check the annotations, write the manifest."""
    texts = RAW / "texts"
    texts.mkdir(parents=True, exist_ok=True)
    annotations = RAW / "annotated_rct_dataset.csv"
    with httpx.Client(timeout=TIMEOUT_S, follow_redirects=True) as client:
        _fetch(client, f"{BASE_URL}/{ANNOTATIONS_PATH}", annotations)
        if _sha256(annotations) != ANNOTATIONS_SHA256:
            print(f"{annotations} does not match the pinned sha256; delete it and retry")
            return 1
        names = sorted({triplet.text_file for triplet in read_annotations(annotations)})
        for index, name in enumerate(names, start=1):
            _fetch(client, f"{BASE_URL}/{TEXT_FOLDER}/{name}", texts / name)
            if index % 20 == 0:
                print(f"  {index} of {len(names)} texts")
    manifest = {
        "source": SOURCE_REPOSITORY,
        "commit": SOURCE_COMMIT,
        "licence": "Apache-2.0",
        "files": {
            path.relative_to(RAW).as_posix(): _sha256(path)
            for path in sorted([annotations, *texts.glob("*.md")])
        },
    }
    (RAW / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"benchmark ready in {RAW}: {len(names)} texts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
