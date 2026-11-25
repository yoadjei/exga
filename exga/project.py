"""project workflows: the store plus the pure modules, in the order the method needs.

the app and the command line call these, so the audit-and-recalibrate loop (spec 5.6) exists
once. every function takes the time as an argument; none reads the clock.

a project is one folder (ADR 0010): project.sqlite, the uploaded papers/ named by their
sha256, and the model response cache/. stored paths are relative to the folder, so a project
can be moved or copied whole.
"""

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from exga.audit import audit_record, draw_audit, recalibrate
from exga.decide import apply_thresholds
from exga.errors import ConfigError, PdfParseError
from exga.extract import extract_pairs, load_prompts, parse_failure_rate
from exga.gold import load_gold
from exga.labels import calibration_records
from exga.llm.base import LLMClient
from exga.llm.cache import CachedLLMClient
from exga.papers import PDF_SUFFIXES, TEXT_SUFFIXES, Skipped, load_document
from exga.schemas import CalibrationRecord, Document, Extraction, FieldSpec, ThresholdResult
from exga.score import score_item
from exga.settings import DocumentSettings, Settings
from exga.store import ProjectStore, ThresholdVersion

DATABASE = "project.sqlite"
PAPERS = "papers"
CACHE = "cache"


@dataclass(frozen=True)
class Project:
    """an open project folder."""

    root: Path
    store: ProjectStore

    @property
    def papers_dir(self) -> Path:
        """where uploaded papers are kept, named by their sha256."""
        return self.root / PAPERS

    @property
    def cache_dir(self) -> Path:
        """the model response cache, so an interrupted run resumes without new requests."""
        return self.root / CACHE


@dataclass(frozen=True)
class RunSummary:
    """what one extraction run did."""

    extracted: int
    """items extracted and saved."""
    failed_requests: int
    """items whose model requests failed; they are not saved, so the next run retries them."""
    errors: tuple[str, ...]
    """one line per failed item: "paper · field: error"."""
    parse_failure_rate: float | None
    """share of answers still unusable after repair (the P3 check); None without answers."""
    skipped: tuple[Skipped, ...]
    """papers whose stored file could not be read."""


def create_project(root: Path, specs: Sequence[FieldSpec]) -> Project:
    """make a project in root (created if missing) with the given fields.

    raises ConfigError when root already holds a project: a project is never overwritten.
    """
    if (root / DATABASE).exists():
        raise ConfigError(f"{root} already holds a project; open it instead")
    (root / PAPERS).mkdir(parents=True, exist_ok=True)
    (root / CACHE).mkdir(exist_ok=True)
    project = Project(root, ProjectStore(root / DATABASE))
    project.store.save_fields(specs)
    return project


def open_project(root: Path) -> Project:
    """open the project in root; raises ConfigError when there is none."""
    if not (root / DATABASE).is_file():
        raise ConfigError(f"no project in {root}")
    (root / PAPERS).mkdir(exist_ok=True)
    (root / CACHE).mkdir(exist_ok=True)
    return Project(root, ProjectStore(root / DATABASE))


def add_paper_file(
    project: Project, filename: str, data: bytes, settings: DocumentSettings, at: datetime
) -> Document:
    """store an uploaded paper as papers/<sha256><suffix> and record it under its own name.

    only the base name of filename is kept, and it is never used as a path. adding the same
    bytes again changes nothing. raises PdfParseError, leaving no file or record behind, when
    the paper has the wrong type or cannot be read.
    """
    name = Path(filename).name
    suffix = Path(name).suffix.lower()
    if suffix not in PDF_SUFFIXES | TEXT_SUFFIXES:
        raise PdfParseError(f"{name} is neither a PDF nor a .md or .txt file")
    relative = Path(PAPERS) / f"{hashlib.sha256(data).hexdigest()}{suffix}"
    path = project.root / relative
    existed = path.exists()
    if not existed:
        path.write_bytes(data)
    try:
        document = load_document(path, settings, filename=name)
    except PdfParseError:
        if not existed:
            path.unlink()
        raise
    project.store.add_paper(document, relative, at)
    return document


def project_documents(
    project: Project, settings: DocumentSettings
) -> tuple[list[Document], list[Skipped]]:
    """load every stored paper in the order added; unreadable ones are returned as Skipped."""
    documents: list[Document] = []
    skipped: list[Skipped] = []
    for paper in project.store.papers():
        if paper.path is None:
            skipped.append(Skipped(paper.filename, "the project holds no file for this paper"))
            continue
        try:
            documents.append(load_document(project.root / paper.path, settings, paper.filename))
        except PdfParseError as exc:
            skipped.append(Skipped(paper.filename, str(exc)))
    return documents, skipped


def run_extraction(
    project: Project,
    client: LLMClient,
    settings: Settings,
    at: datetime,
    progress: Callable[[int, int], None] | None = None,
) -> RunSummary:
    """extract, score and save every (paper, field) item the project does not hold yet.

    requests go through the project's response cache. items whose requests failed are not
    saved, so the next run retries them. BudgetExceededError propagates; the answers received
    before it stay cached. progress(done, total) is called as items finish.
    """
    documents, skipped = project_documents(project, settings.document)
    specs = project.store.fields()
    held = {(e.paper_id, e.field) for e in project.store.extractions()}
    pairs = [
        (document, spec)
        for document in documents
        for spec in specs
        if (document.paper_id, spec.name) not in held
    ]
    cached = CachedLLMClient(client, project.cache_dir)
    prompts = load_prompts(settings.extraction.prompt_version)
    items = extract_pairs(pairs, cached, prompts, settings, progress)
    by_id = {document.paper_id: document for document in documents}
    by_name = {spec.name: spec for spec in specs}
    answered = [item for item in items if item.error is None]
    scored = [
        score_item(item, by_id[item.paper_id], by_name[item.field], settings) for item in answered
    ]
    save_scored(project.store, scored, at)
    errors = tuple(
        f"{by_id[item.paper_id].filename} · {item.field}: {item.error}"
        for item in items
        if item.error is not None
    )
    return RunSummary(
        extracted=len(answered),
        failed_requests=len(errors),
        errors=errors,
        parse_failure_rate=parse_failure_rate(items),
        skipped=tuple(skipped),
    )


def import_gold_file(
    project: Project, path: Path, settings: Settings, at: datetime
) -> ThresholdVersion:
    """turn a gold file of this project's papers into annotation records, then recalibrate.

    only items already extracted get a record. raises ConfigError for a malformed gold file.
    """
    specs = project.store.fields()
    records = calibration_records(
        project.store.extractions(),
        load_gold(path, specs),
        specs,
        settings.matching,
        source="annotation",
        created_at=at,
    )
    return import_records(project.store, records, settings, at)


def current_thresholds(store: ProjectStore) -> dict[str, ThresholdResult]:
    """the newest logged threshold of every field; empty before the first calibration."""
    log = store.threshold_log()
    return log[-1].results if log else {}


def project_settings(store: ProjectStore, settings: Settings) -> Settings:
    """settings with the alpha and delta of the project's latest calibration.

    a person sets the error level once (Calibrate page); audits and imports must recalibrate
    at that level, not at the default. before any calibration, settings are returned as given.
    """
    results = list(current_thresholds(store).values())
    if not results:
        return settings
    calibration = settings.calibration.model_copy(
        update={"alpha": results[0].alpha, "delta": results[0].delta}
    )
    return settings.model_copy(update={"calibration": calibration})


def save_scored(store: ProjectStore, extractions: Sequence[Extraction], at: datetime) -> None:
    """store new extractions with decisions under the current thresholds."""
    store.save_extractions(apply_thresholds(extractions, current_thresholds(store)), at)


def import_records(
    store: ProjectStore, records: Sequence[CalibrationRecord], settings: Settings, at: datetime
) -> ThresholdVersion:
    """append benchmark or annotation records, then recalibrate.

    raises ConfigError for random-audit records, which only `finish_audit` may add.
    """
    if any(record.source == "random_audit" for record in records):
        raise ConfigError("random-audit records come only from completed audit batches")
    store.add_records(records)
    return recalibrate_project(store, settings, at)


def recalibrate_project(store: ProjectStore, settings: Settings, at: datetime) -> ThresholdVersion:
    """recompute every field's threshold from all records, log it, and re-decide every item."""
    records = store.records()
    results = recalibrate(records, store.fields(), settings.calibration)
    version = store.log_thresholds(results, len(records), at)
    store.save_extractions(apply_thresholds(store.extractions(), results), at)
    return store.threshold_log()[version - 1]


def draw_next_audit(store: ProjectStore, settings: Settings, at: datetime) -> int | None:
    """the open audit batch, or a new one drawn from items not yet audited; None if none remain.

    batch k is drawn with seed settings.audit.seed + k, so the draws can be replayed.
    """
    open_batch = store.open_audit()
    if open_batch is not None:
        return open_batch
    audited = store.audited()
    candidates = [e for e in store.extractions() if (e.paper_id, e.field) not in audited]
    if not candidates:
        return None
    seed = settings.audit.seed + store.audit_batch_count()
    return store.start_audit(draw_audit(candidates, settings.audit, seed), seed, at)


def finish_audit(
    store: ProjectStore, batch_id: int, settings: Settings, at: datetime
) -> ThresholdVersion:
    """turn a fully checked batch into records, close it, and recalibrate.

    skipped items give no record. raises ConfigError while items are unchecked.
    """
    specs = {spec.name: spec for spec in store.fields()}
    extractions = {(e.paper_id, e.field): e for e in store.extractions()}
    records = [
        audit_record(
            extractions[item.paper_id, item.field],
            item.checked_value,
            specs[item.field],
            settings.matching,
            at,
        )
        for item in store.audit_items(batch_id)
        if item.status == "checked"
    ]
    store.complete_audit(batch_id, records, at)
    return recalibrate_project(store, settings, at)
