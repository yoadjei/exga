"""the project database: one SQLite file per project (spec 0A.5, 6, 7.7).

opening a store applies any numbered migration in exga/migrations/ that the file has not
seen, recorded in `schema_version`. each method opens its own connection, so a store can be
shared by threads (Streamlit runs each session in one). calibration records and the threshold
log are append-only, enforced by the database itself.
"""

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from exga.errors import ConfigError
from exga.schemas import (
    CalibrationRecord,
    Document,
    Extraction,
    FieldSpec,
    ThresholdResult,
)

MIGRATIONS = Path(__file__).parent / "migrations"
_BUSY_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class PaperRow:
    """a paper known to the project."""

    paper_id: str
    filename: str
    source: str
    path: Path | None


@dataclass(frozen=True)
class AuditItem:
    """one drawn item of an audit batch and what the person found."""

    batch_id: int
    paper_id: str
    field: str
    status: str
    checked_value: str | None


@dataclass(frozen=True)
class ThresholdVersion:
    """one entry of the threshold log."""

    version: int
    created_at: datetime
    n_records: int
    results: dict[str, ThresholdResult]


class ProjectStore:
    """typed access to one project's database file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            _migrate(connection)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=_BUSY_TIMEOUT_S)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:  # commits, or rolls back on an exception
                yield connection
        finally:
            connection.close()

    def schema_version(self) -> int:
        """the number of the last migration applied."""
        with self._connect() as connection:
            return _current_version(connection)

    def save_fields(self, specs: Sequence[FieldSpec]) -> None:
        """replace the project's field list."""
        with self._connect() as connection:
            connection.execute("DELETE FROM fields")
            connection.executemany(
                "INSERT INTO fields (position, name, spec) VALUES (?, ?, ?)",
                [(index, spec.name, spec.model_dump_json()) for index, spec in enumerate(specs)],
            )

    def fields(self) -> tuple[FieldSpec, ...]:
        """the field list in its saved order."""
        with self._connect() as connection:
            rows = connection.execute("SELECT spec FROM fields ORDER BY position").fetchall()
        return tuple(FieldSpec.model_validate_json(spec) for (spec,) in rows)

    def add_paper(self, document: Document, path: Path | None, at: datetime) -> None:
        """record a paper; adding the same file again only updates its location."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO papers (paper_id, filename, source, path, added_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (paper_id) DO UPDATE SET path = excluded.path",
                (
                    document.paper_id,
                    document.filename,
                    document.source,
                    None if path is None else str(path),
                    at.isoformat(),
                ),
            )

    def papers(self) -> list[PaperRow]:
        """every paper, in the order added."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT paper_id, filename, source, path FROM papers ORDER BY added_at, filename"
            ).fetchall()
        return [
            PaperRow(paper_id, filename, source, None if path is None else Path(path))
            for paper_id, filename, source, path in rows
        ]

    def save_extractions(self, extractions: Sequence[Extraction], at: datetime) -> None:
        """insert or replace extractions, keyed by (paper, field)."""
        with self._connect() as connection:
            connection.executemany(
                "INSERT INTO extractions (paper_id, field, record, score, decision, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (paper_id, field) DO UPDATE SET record = excluded.record,"
                " score = excluded.score, decision = excluded.decision,"
                " updated_at = excluded.updated_at",
                [
                    (e.paper_id, e.field, e.model_dump_json(), e.score, e.decision, at.isoformat())
                    for e in extractions
                ],
            )

    def extractions(self) -> list[Extraction]:
        """every extraction, ordered by paper, then field."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record FROM extractions ORDER BY paper_id, field"
            ).fetchall()
        return [Extraction.model_validate_json(record) for (record,) in rows]

    def add_records(self, records: Sequence[CalibrationRecord]) -> None:
        """append calibration records; they can never be changed afterwards."""
        with self._connect() as connection:
            _insert_records(connection, records)

    def records(self) -> list[CalibrationRecord]:
        """every calibration record, oldest first."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT paper_id, field, field_group, score, wrong, source, created_at"
                " FROM calibration_records ORDER BY id"
            ).fetchall()
        return [
            CalibrationRecord(
                paper_id=paper_id,
                field=field,
                group=group,
                score=score,
                wrong=bool(wrong),
                source=source,
                created_at=datetime.fromisoformat(created_at),
            )
            for paper_id, field, group, score, wrong, source, created_at in rows
        ]

    def start_audit(self, items: Sequence[Extraction], seed: int, at: datetime) -> int:
        """record a drawn batch and return its id."""
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO audit_batches (seed, drawn_at) VALUES (?, ?)", (seed, at.isoformat())
            )
            batch_id = int(cursor.lastrowid or 0)
            connection.executemany(
                "INSERT INTO audit_items (batch_id, paper_id, field) VALUES (?, ?, ?)",
                [(batch_id, item.paper_id, item.field) for item in items],
            )
        return batch_id

    def audit_items(self, batch_id: int) -> list[AuditItem]:
        """the items of one batch, in the order drawn."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT batch_id, paper_id, field, status, checked_value FROM audit_items"
                " WHERE batch_id = ? ORDER BY rowid",
                (batch_id,),
            ).fetchall()
        return [AuditItem(*row) for row in rows]

    def set_audit_result(
        self,
        batch_id: int,
        paper_id: str,
        field: str,
        *,
        checked_value: str | None,
        skipped: bool,
        at: datetime,
    ) -> None:
        """store what a person found for one drawn item, or that they skipped it.

        raises ConfigError when the item is not in an open batch.
        """
        status = "skipped" if skipped else "checked"
        with self._connect() as connection:
            open_batch = connection.execute(
                "SELECT 1 FROM audit_batches WHERE id = ? AND completed_at IS NULL", (batch_id,)
            ).fetchone()
            cursor = connection.execute(
                "UPDATE audit_items SET status = ?, checked_value = ?, checked_at = ?"
                " WHERE batch_id = ? AND paper_id = ? AND field = ?",
                (
                    status,
                    None if skipped else checked_value,
                    at.isoformat(),
                    batch_id,
                    paper_id,
                    field,
                ),
            )
            if open_batch is None or cursor.rowcount != 1:
                raise ConfigError(
                    f"no open audit batch {batch_id} holds {field} of {paper_id[:12]}…"
                )

    def complete_audit(
        self, batch_id: int, records: Sequence[CalibrationRecord], at: datetime
    ) -> None:
        """close a batch and append its records in one transaction.

        raises ConfigError while any item is still pending or the batch is already closed.
        """
        with self._connect() as connection:
            pending = connection.execute(
                "SELECT COUNT(*) FROM audit_items WHERE batch_id = ? AND status = 'pending'",
                (batch_id,),
            ).fetchone()[0]
            if pending:
                raise ConfigError(f"audit batch {batch_id} has {pending} unchecked items")
            cursor = connection.execute(
                "UPDATE audit_batches SET completed_at = ? WHERE id = ? AND completed_at IS NULL",
                (at.isoformat(), batch_id),
            )
            if cursor.rowcount != 1:
                raise ConfigError(f"audit batch {batch_id} is not open")
            _insert_records(connection, records)

    def audit_batch_count(self) -> int:
        """how many audit batches have been drawn, open or closed."""
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM audit_batches").fetchone()[0])

    def open_audit(self) -> int | None:
        """the id of the batch still being checked, if any."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM audit_batches WHERE completed_at IS NULL ORDER BY id LIMIT 1"
            ).fetchone()
        return None if row is None else int(row[0])

    def audited(self) -> set[tuple[str, str]]:
        """every (paper, field) already drawn in any batch; these are not drawn again."""
        with self._connect() as connection:
            rows = connection.execute("SELECT DISTINCT paper_id, field FROM audit_items").fetchall()
        return {(paper_id, field) for paper_id, field in rows}

    def add_correction(self, paper_id: str, field: str, value: str | None, at: datetime) -> None:
        """record a value a person fixed outside an audit; it never enters calibration."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO corrections (paper_id, field, value, created_at) VALUES (?, ?, ?, ?)",
                (paper_id, field, value, at.isoformat()),
            )

    def corrections(self) -> dict[tuple[str, str], str | None]:
        """the latest correction of each (paper, field)."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT paper_id, field, value FROM corrections ORDER BY id"
            ).fetchall()
        return {(paper_id, field): value for paper_id, field, value in rows}

    def log_thresholds(
        self, results: dict[str, ThresholdResult], n_records: int, at: datetime
    ) -> int:
        """append a threshold version and return its number."""
        payload = json.dumps({field: r.model_dump(mode="json") for field, r in results.items()})
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO threshold_log (created_at, n_records, results) VALUES (?, ?, ?)",
                (at.isoformat(), n_records, payload),
            )
        return int(cursor.lastrowid or 0)

    def threshold_log(self) -> list[ThresholdVersion]:
        """every threshold version, oldest first."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT version, created_at, n_records, results FROM threshold_log ORDER BY version"
            ).fetchall()
        return [
            ThresholdVersion(
                version=version,
                created_at=datetime.fromisoformat(created_at),
                n_records=n_records,
                results={
                    field: ThresholdResult.model_validate(result)
                    for field, result in json.loads(results).items()
                },
            )
            for version, created_at, n_records, results in rows
        ]


def _insert_records(connection: sqlite3.Connection, records: Sequence[CalibrationRecord]) -> None:
    connection.executemany(
        "INSERT INTO calibration_records"
        " (paper_id, field, field_group, score, wrong, source, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r.paper_id,
                r.field,
                r.group,
                r.score,
                int(r.wrong),
                r.source,
                r.created_at.isoformat(),
            )
            for r in records
        ],
    )


def _current_version(connection: sqlite3.Connection) -> int:
    connection.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = connection.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def _migrate(connection: sqlite3.Connection) -> None:
    current = _current_version(connection)
    for path in sorted(MIGRATIONS.glob("*.sql")):
        number = int(path.name.split("_", 1)[0])
        if number <= current:
            continue
        # executescript commits first; each migration runs in its own explicit transaction
        connection.executescript(
            "BEGIN;\n"
            + path.read_text(encoding="utf-8")
            + f"\nINSERT INTO schema_version (version) VALUES ({number});\nCOMMIT;"
        )
