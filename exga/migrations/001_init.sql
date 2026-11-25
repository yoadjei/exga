-- 001: the first project schema (spec 0A.5, 5.6).
-- calibration records and the threshold log are append-only: triggers refuse changes.

CREATE TABLE fields (
    position INTEGER NOT NULL,
    name TEXT PRIMARY KEY,
    spec TEXT NOT NULL              -- FieldSpec as JSON
);

CREATE TABLE papers (
    paper_id TEXT PRIMARY KEY,      -- sha256 of the file
    filename TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('pdf', 'text')),
    path TEXT,                      -- where the file is, to render highlights; may be NULL
    added_at TEXT NOT NULL
);

CREATE TABLE extractions (
    paper_id TEXT NOT NULL REFERENCES papers (paper_id),
    field TEXT NOT NULL,
    record TEXT NOT NULL,           -- Extraction as JSON
    score REAL NOT NULL,
    decision TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (paper_id, field)
);

CREATE TABLE calibration_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL,
    field TEXT NOT NULL,
    field_group TEXT NOT NULL,
    score REAL NOT NULL,
    wrong INTEGER NOT NULL CHECK (wrong IN (0, 1)),
    source TEXT NOT NULL CHECK (source IN ('benchmark', 'annotation', 'random_audit')),
    created_at TEXT NOT NULL
);

CREATE TRIGGER calibration_records_no_update BEFORE UPDATE ON calibration_records
BEGIN
    SELECT RAISE(ABORT, 'calibration records are append-only');
END;

CREATE TRIGGER calibration_records_no_delete BEFORE DELETE ON calibration_records
BEGIN
    SELECT RAISE(ABORT, 'calibration records are append-only');
END;

CREATE TABLE audit_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seed INTEGER NOT NULL,
    drawn_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE audit_items (
    batch_id INTEGER NOT NULL REFERENCES audit_batches (id),
    paper_id TEXT NOT NULL,
    field TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'checked', 'skipped')),
    checked_value TEXT,             -- with status 'checked', NULL means "not reported"
    checked_at TEXT,
    PRIMARY KEY (batch_id, paper_id, field)
);

CREATE TABLE corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id TEXT NOT NULL,
    field TEXT NOT NULL,
    value TEXT,                     -- NULL means "not reported"
    created_at TEXT NOT NULL
);

CREATE TABLE threshold_log (
    version INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    n_records INTEGER NOT NULL,
    results TEXT NOT NULL           -- {field: ThresholdResult} as JSON
);

CREATE TRIGGER threshold_log_no_update BEFORE UPDATE ON threshold_log
BEGIN
    SELECT RAISE(ABORT, 'the threshold log is append-only');
END;

CREATE TRIGGER threshold_log_no_delete BEFORE DELETE ON threshold_log
BEGIN
    SELECT RAISE(ABORT, 'the threshold log is append-only');
END;
