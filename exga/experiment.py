"""the experiments (spec 11, ADR 0011): config, extraction, labelling, evaluation.

`experiments/run.py` is the entry point. extraction costs money and runs only when asked;
evaluation reads the saved samples, so tables are regenerated from configs without new
requests. everything here is deterministic given the config and the samples.
"""

import csv
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, ClassVar, Literal, Self

import numpy as np
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from exga.benchmark import (
    ANNOTATIONS_SHA256,
    SOURCE_COMMIT,
    SOURCE_REPOSITORY,
    Split,
    benchmark_items,
    load_templates,
    load_texts,
    read_annotations,
)
from exga.errors import ConfigError
from exga.evaluate import (
    BASELINES,
    EMPTY,
    FloatArray,
    LabelledItem,
    Metric,
    Outcome,
    SplitRun,
    alpha_exceedances,
    bootstrap_interval,
    run_split,
    updating_curve,
    variant_scores,
)
from exga.extract import extract_pairs, load_prompts, parse_failure_rate
from exga.fields import load_fields
from exga.gold import load_gold
from exga.labels import is_wrong
from exga.llm.base import LLMClient
from exga.llm.cache import CachedLLMClient
from exga.manifest import content_hash
from exga.papers import load_folder
from exga.records import load_jsonl, save_jsonl
from exga.schemas import (
    CalibrationRecord,
    Document,
    FieldGroup,
    FieldSamples,
    FieldSpec,
    RecordSource,
)
from exga.score import score_item
from exga.settings import (
    CalibrationSettings,
    DocumentSettings,
    HostedSettings,
    ScoreSettings,
    Settings,
    SplitSettings,
)
from exga.splits import PaperSplit, split_papers

DEFAULT_VARIANTS = {
    "agreement": ScoreSettings(logprob_weight=0.0, source_weight=0.0),
    "agreement+logprob": ScoreSettings(source_weight=0.0),
    "agreement+source": ScoreSettings(logprob_weight=0.0),
    "combined": ScoreSettings(),
}
"""the signal ablation of spec 11.1.4; "combined" is the deployed default score."""
ANNOTATIONS_FILE = "annotated_rct_dataset.csv"
TEXTS_FOLDER = "texts"
ALL_FIELDS = "all"
Row = dict[str, object]


class ModelConfig(BaseModel):
    """one model to compare; its endpoint settings override the environment's."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    """folder name for this model's samples."""
    hosted: dict[str, object] = Field(default_factory=dict)
    """HostedSettings fields, e.g. base_url, model, prices; the API key comes only from the
    environment, so configs can be committed."""

    @field_validator("hosted")
    @classmethod
    def _no_secret_in_config(cls, hosted: dict[str, object]) -> dict[str, object]:
        if "api_key" in hosted:
            raise ValueError("api_key belongs in the EXGA_HOSTED__API_KEY variable, not a config")
        return hosted

    def settings(self, base: HostedSettings) -> HostedSettings:
        """the environment's endpoint settings with this model's overrides, validated."""
        try:
            return HostedSettings.model_validate({**base.model_dump(), **self.hosted})
        except ValidationError as exc:
            raise ConfigError(f"model {self.name}: {exc}") from exc


class BenchmarkData(BaseModel):
    """the Yun et al. benchmark as downloaded by scripts/download_benchmark.py (ADR 0008)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_source: ClassVar[RecordSource] = "benchmark"

    kind: Literal["benchmark"] = "benchmark"
    folder: Path = Path("data/benchmark/raw")
    split: Split = "TEST"
    item_seed: int = 0
    """seed choosing one triplet per (paper, field) (ADR 0008)."""

    @field_serializer("folder")
    def _posix(self, path: Path) -> str:
        return path.as_posix()

    def inputs(self) -> dict[str, Path]:
        """the files whose hashes a run manifest records."""
        return {"annotations": self.folder / ANNOTATIONS_FILE}

    def provenance(self) -> dict[str, object]:
        """where the data came from, for a run manifest."""
        return {
            "kind": self.kind,
            "repository": SOURCE_REPOSITORY,
            "commit": SOURCE_COMMIT,
            "annotations_sha256": ANNOTATIONS_SHA256,
            "split": self.split,
            "item_seed": self.item_seed,
        }


class AnnotatedData(BaseModel):
    """the owner's annotated set (spec 10.2): a folder of papers, its field list and gold file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_source: ClassVar[RecordSource] = "annotation"

    kind: Literal["annotated"]
    papers: Path
    fields: Path
    gold: Path

    @field_serializer("papers", "fields", "gold")
    def _posix(self, path: Path) -> str:
        return path.as_posix()

    def inputs(self) -> dict[str, Path]:
        """the files whose hashes a run manifest records; papers are named in the samples."""
        return {"fields": self.fields, "gold": self.gold}

    def provenance(self) -> dict[str, object]:
        """where the data came from, for a run manifest."""
        return {"kind": self.kind}


Data = Annotated[BenchmarkData | AnnotatedData, Field(discriminator="kind")]


@dataclass(frozen=True)
class GoldItem:
    """one question to a model: a field of one paper, with its gold value (None: not reported)."""

    document: Document
    spec: FieldSpec
    gold: str | None


class ExperimentConfig(BaseModel):
    """one experiment, as written in experiments/*.yaml (spec 11.2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    data: Data = Field(default_factory=BenchmarkData)
    models: tuple[ModelConfig, ...] = Field(min_length=1)
    alphas: tuple[float, ...] = (0.05, 0.1, 0.2)
    delta: float = Field(default=0.1, gt=0.0, lt=1.0)
    repetitions: int = Field(default=50, ge=1)
    bootstrap: int = Field(default=1000, ge=10)
    cutoff: float = Field(default=0.8, ge=0.0, le=1.0)
    """the uncalibrated fixed cut-off baseline."""
    audit_batch: int = Field(default=10, ge=1)
    seed: int = 0
    """split r uses seed + r; split 0 is the primary split, which carries the intervals."""
    variants: dict[str, ScoreSettings] = Field(default_factory=lambda: dict(DEFAULT_VARIANTS))
    primary_variant: str = "combined"
    """the score of the updating curve, and the one the thesis reports first."""
    runs: Path = Path("runs")
    """samples go to runs/<name>/<model>/; the response cache is shared in runs/cache."""
    results: Path = Path("results")

    @field_validator("alphas")
    @classmethod
    def _alphas_are_error_levels(cls, alphas: tuple[float, ...]) -> tuple[float, ...]:
        if not alphas or any(not 0 < alpha < 1 for alpha in alphas):
            raise ValueError("alphas must be one or more numbers between 0 and 1")
        return alphas

    @model_validator(mode="after")
    def _names_are_consistent(self) -> Self:
        if self.primary_variant not in self.variants:
            raise ValueError(f"primary_variant {self.primary_variant!r} is not in variants")
        names = [model.name for model in self.models]
        if len(names) != len(set(names)):
            raise ValueError("model names must be distinct")
        return self

    @field_serializer("runs", "results")
    def _posix(self, path: Path) -> str:
        # forward slashes on every system, so a config hashes, and names its results folder,
        # the same on Windows and Linux
        return path.as_posix()

    def samples_path(self, model: ModelConfig) -> Path:
        """where a model's samples are saved."""
        return self.runs / self.name / model.name / "samples.jsonl"

    def results_folder(self) -> Path:
        """results/<name>-<first 8 hex digits of the config's hash> (ADR 0011)."""
        return self.results / f"{self.name}-{content_hash(self.model_dump(mode='json'))[:8]}"


def load_config(path: Path) -> ExperimentConfig:
    """read and validate an experiment config; raises ConfigError naming each problem."""
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read experiment config {path}: {exc}") from exc
    try:
        return ExperimentConfig.model_validate(content)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'config'}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigError(f"experiment config {path}: {problems}") from exc


def load_items(config: ExperimentConfig, settings: DocumentSettings) -> list[GoldItem]:
    """the config's dataset as items with gold values.

    raises ConfigError when the data are missing or malformed, or when the gold file names a
    paper that is not in the papers folder or could not be read.
    """
    if isinstance(config.data, AnnotatedData):
        return _annotated_items(config.data, settings)
    return _benchmark_items(config.data)


def _annotated_items(data: AnnotatedData, settings: DocumentSettings) -> list[GoldItem]:
    specs = load_fields(data.fields)
    gold = load_gold(data.gold, specs)
    documents, skipped = load_folder(data.papers, settings)
    absent = {paper for paper, _ in gold} - {document.paper_id for document in documents}
    if absent:
        unreadable = (
            f"; unreadable files: {', '.join(s.filename for s in skipped)}" if skipped else ""
        )
        raise ConfigError(
            f"{data.gold} has values for {len(absent)} paper(s) not found in {data.papers}"
            f"{unreadable}"
        )
    return [
        GoldItem(document, spec, gold[document.paper_id, spec.name])
        for document in documents
        for spec in specs
        if (document.paper_id, spec.name) in gold
    ]


def _benchmark_items(data: BenchmarkData) -> list[GoldItem]:
    annotations = data.folder / ANNOTATIONS_FILE
    if not annotations.is_file():
        raise ConfigError(
            f"benchmark not found in {data.folder}; run scripts/download_benchmark.py"
        )
    triplets = read_annotations(annotations)
    texts = load_texts(data.folder / TEXTS_FOLDER, triplets)
    items = benchmark_items(
        triplets, texts, load_templates(), split=data.split, seed=data.item_seed
    )
    return [GoldItem(item.document, item.spec, item.gold) for item in items]


@dataclass(frozen=True)
class ExtractionRun:
    """what one model's extraction did."""

    items: int
    failed_requests: int
    parse_failure_rate: float | None
    requests_sent: int
    requests_from_cache: int


def extract(
    config: ExperimentConfig,
    model: ModelConfig,
    items: Sequence[GoldItem],
    client: LLMClient,
    settings: Settings,
    progress: Callable[[int, int], None] | None = None,
) -> ExtractionRun:
    """ask the model about every item through the shared response cache, and save the
    samples with a run summary beside them."""
    cached = CachedLLMClient(client, config.runs / "cache")
    prompts = load_prompts(settings.extraction.prompt_version)
    samples = extract_pairs(
        [(item.document, item.spec) for item in items], cached, prompts, settings, progress
    )
    path = config.samples_path(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_jsonl(samples, path)
    run = ExtractionRun(
        items=len(samples),
        failed_requests=sum(sample.error is not None for sample in samples),
        parse_failure_rate=parse_failure_rate(samples),
        requests_sent=cached.misses,
        requests_from_cache=cached.hits,
    )
    summary = {"model_id": cached.model_id, "prompt_version": prompts.version, **asdict(run)}
    (path.parent / "run.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return run


def load_samples(config: ExperimentConfig, model: ModelConfig) -> list[FieldSamples]:
    """a model's saved samples; raises ConfigError when it has not been extracted."""
    path = config.samples_path(model)
    if not path.is_file():
        raise ConfigError(
            f"no samples for model {model.name} at {path}; run experiments/run.py extract first"
        )
    return load_jsonl(path, FieldSamples)


def label(
    items: Sequence[GoldItem], samples: Sequence[FieldSamples], settings: Settings
) -> list[LabelledItem]:
    """score every item's samples and mark it wrong or right against its gold value.

    raises ConfigError when samples and items do not match one to one, e.g. samples from
    another config or an interrupted extraction.
    """
    by_key = {(item.document.paper_id, item.spec.name): item for item in items}
    found = {(sample.paper_id, sample.field): sample for sample in samples}
    missing = by_key.keys() - found.keys()
    unknown = found.keys() - by_key.keys()
    if missing or unknown:
        raise ConfigError(
            f"samples do not match the items: {len(missing)} items have no samples "
            f"and {len(unknown)} samples have no item; run the extraction again"
        )
    labelled = []
    for key, item in by_key.items():
        extraction = score_item(found[key], item.document, item.spec, settings)
        labelled.append(
            LabelledItem(
                paper_id=item.document.paper_id,
                field=item.spec.name,
                group=item.spec.group,
                signals=extraction.signals,
                wrong=is_wrong(extraction, item.gold, item.spec, settings.matching),
                failed=extraction.failed,
            )
        )
    return labelled


def item_records(
    items: Sequence[LabelledItem], weights: ScoreSettings, source: RecordSource, at: datetime
) -> list[CalibrationRecord]:
    """every labelled item as a calibration record, scored with weights.

    with the deployed weights (`Settings.score`) these are the records file a project imports
    on its Calibrate page; they certify its papers only if those resemble these items and
    were extracted with the same model and prompt.
    """
    scores = variant_scores(items, weights).tolist()
    return [
        CalibrationRecord(
            paper_id=item.paper_id,
            field=item.field,
            group=item.group,
            score=score,
            wrong=item.wrong,
            source=source,
            created_at=at,
        )
        for item, score in zip(items, scores, strict=True)
    ]


@dataclass
class Tables:
    """the spec 11.2 tables as rows, ready for CSV."""

    by_group: list[Row] = field(default_factory=list)
    by_field: list[Row] = field(default_factory=list)
    baselines: list[Row] = field(default_factory=list)
    updating: list[Row] = field(default_factory=list)


def evaluate(
    config: ExperimentConfig,
    labelled: Mapping[str, Sequence[LabelledItem]],
    progress: Callable[[str], None] | None = None,
) -> Tables:
    """every model, score variant and error level, over the configured random splits."""
    tables = Tables()
    for model, items in labelled.items():
        specs = _specs(items)
        papers = sorted({item.paper_id for item in items})
        splits = [
            split_papers(papers, config.seed + repetition, SplitSettings())
            for repetition in range(config.repetitions)
        ]
        for variant, weights in config.variants.items():
            scores = variant_scores(items, weights)
            runs: list[SplitRun] = []
            for alpha in config.alphas:
                if progress is not None:
                    progress(f"{model} · {variant} · alpha {alpha}")
                settings = CalibrationSettings(alpha=alpha, delta=config.delta)
                runs = [
                    run_split(items, scores, specs, split, settings, config.cutoff)
                    for split in splits
                ]
                key: Row = {"model": model, "variant": variant, "alpha": alpha}
                units = _units(specs)
                tables.by_group += [
                    _summary(config, key, "group", name, fields, items, runs, alpha)
                    for name, fields in units.items()
                ]
                tables.by_field += [
                    _summary(config, key, "field", spec.name, [spec.name], items, runs, alpha)
                    for spec in specs
                ]
                if variant == config.primary_variant:
                    tables.updating += _updating(config, key, items, scores, specs, splits, alpha)
            # the baselines do not depend on alpha; the last alpha's runs serve
            tables.baselines += _baselines(config, model, variant, runs)
    return tables


def _specs(items: Sequence[LabelledItem]) -> list[FieldSpec]:
    groups: dict[str, FieldGroup] = {}
    for item in items:
        groups.setdefault(item.field, item.group)
    return [
        FieldSpec(name=name, description=name.replace("_", " "), group=group)
        for name, group in groups.items()
    ]


def _units(specs: Sequence[FieldSpec]) -> dict[str, list[str]]:
    """all fields together, then each field group."""
    units = {ALL_FIELDS: [spec.name for spec in specs]}
    for spec in specs:
        units.setdefault(spec.group, []).append(spec.name)
    return units


def _summary(
    config: ExperimentConfig,
    key: Row,
    level: str,
    unit: str,
    fields: Sequence[str],
    items: Sequence[LabelledItem],
    runs: Sequence[SplitRun],
    alpha: float,
) -> Row:
    primary = runs[0]
    result = _total(primary, fields)
    mask = primary.test & np.isin([item.field for item in items], list(fields))
    papers = [items[index].paper_id for index in np.flatnonzero(mask).tolist()]
    wrong = np.array([item.wrong for item in items])[mask]

    def interval(metric: Metric) -> tuple[float | None, float | None]:
        bounds = bootstrap_interval(
            papers, primary.accepted[mask], wrong, metric, config.bootstrap, seed=config.seed
        )
        return (None, None) if bounds is None else bounds

    per_split = [_total(run, fields) for run in runs]
    certified = [run.fields[name].certified for run in runs for name in fields]
    above, measured = alpha_exceedances(
        (run.fields[name] for run in runs for name in fields), alpha
    )
    acceptance_low, acceptance_high = interval("acceptance_rate")
    error_low, error_high = interval("realised_error")
    return {
        **key,
        level: unit,
        "test_items": result.items,
        "raw_accuracy": result.raw_accuracy,
        "acceptance_rate": result.acceptance_rate,
        "acceptance_low": acceptance_low,
        "acceptance_high": acceptance_high,
        "realised_error": result.realised_error,
        "error_low": error_low,
        "error_high": error_high,
        "coverage": result.coverage,
        "certified": all(primary.fields[name].certified for name in fields),
        "mean_acceptance_rate": _mean([outcome.acceptance_rate for outcome in per_split]),
        "mean_realised_error": _mean([outcome.realised_error for outcome in per_split]),
        "certified_share": sum(certified) / len(certified),
        "splits": len(runs),
        "error_above_alpha": above,
        "error_measured": measured,
        "error_above_alpha_rate": above / measured if measured else None,
    }


def _baselines(
    config: ExperimentConfig, model: str, variant: str, runs: Sequence[SplitRun]
) -> list[Row]:
    return [
        {
            "model": model,
            "variant": variant,
            "baseline": name,
            "cutoff": config.cutoff if name == "fixed_cutoff" else None,
            "acceptance_rate": runs[0].baselines[name].acceptance_rate,
            "realised_error": runs[0].baselines[name].realised_error,
            "mean_acceptance_rate": _mean([run.baselines[name].acceptance_rate for run in runs]),
            "mean_realised_error": _mean([run.baselines[name].realised_error for run in runs]),
        }
        for name in BASELINES
    ]


def _updating(
    config: ExperimentConfig,
    key: Row,
    items: Sequence[LabelledItem],
    scores: FloatArray,
    specs: Sequence[FieldSpec],
    splits: Sequence[PaperSplit],
    alpha: float,
) -> list[Row]:
    settings = CalibrationSettings(alpha=alpha, delta=config.delta)
    curves = [
        updating_curve(items, scores, specs, split, settings, config.audit_batch, config.seed + r)
        for r, split in enumerate(splits)
    ]
    # papers have 4 or 6 fields, so audit pools, and curves, differ in length between splits
    steps = min(len(curve) for curve in curves)
    return [
        {
            "model": key["model"],
            "variant": key["variant"],
            "alpha": alpha,
            "audit_records": min(curve[step].records for curve in curves),
            "mean_acceptance_rate": _mean(
                [curve[step].outcome.acceptance_rate for curve in curves]
            ),
            "mean_realised_error": _mean([curve[step].outcome.realised_error for curve in curves]),
            "splits": len(curves),
        }
        for step in range(steps)
    ]


def _total(run: SplitRun, fields: Sequence[str]) -> Outcome:
    return sum((run.fields[name].outcome for name in fields), EMPTY)


def _mean(values: Sequence[float | None]) -> float | None:
    defined = [value for value in values if value is not None]
    return sum(defined) / len(defined) if defined else None


def write_tables(tables: Tables, folder: Path) -> list[Path]:
    """write each table as <name>.csv in folder; an empty table gives an empty file.

    numbers keep 6 significant digits, None is an empty cell and booleans are true/false.
    """
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, rows in asdict(tables).items():
        path = folder / f"{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
                writer.writeheader()
                writer.writerows({key: _cell(value) for key, value in row.items()} for row in rows)
        paths.append(path)
    return paths


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
