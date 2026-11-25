"""Export page: the results table and the guarantees behind it (spec 7.11 page 7)."""

import json
from typing import get_args

import streamlit as st

from exga.app import ui
from exga.export import csv_bytes, export_rows
from exga.messages import status
from exga.project import current_thresholds
from exga.schemas import Decision

project = ui.require_project()
store = project.store

st.title("Export")
extractions = store.extractions()
if not extractions:
    st.info("Nothing is extracted yet. Upload papers and run the extraction first.")
    ui.link("run")
    st.stop()

columns = st.columns(3)
for column, decision in zip(columns, get_args(Decision), strict=True):
    column.metric(status(decision), sum(item.decision == decision for item in extractions))

filenames = {paper.paper_id: paper.filename for paper in store.papers()}
rows = export_rows(extractions, filenames, store.checked_values())
st.download_button(
    "Download results.csv",
    csv_bytes(rows),
    file_name="results.csv",
    mime="text/csv",
    type="primary",
)
st.caption(
    "One row per paper and field. value is the model's answer (NR: not reported; empty: no "
    "usable answer); decision is Accepted, Check or Not certifiable; checked_value is what a "
    "person entered in an audit or a correction, when anyone did."
)

log = store.threshold_log()
if log:
    latest = log[-1]
    guarantees = {
        "threshold_version": latest.version,
        "created_at": latest.created_at.isoformat(),
        "checked_values": latest.n_records,
        "fields": {
            field: result.model_dump(mode="json")
            for field, result in current_thresholds(store).items()
        },
    }
    st.download_button(
        "Download guarantees.json",
        json.dumps(guarantees, indent=2),
        file_name="guarantees.json",
        mime="application/json",
    )
    st.caption("The thresholds and bounds behind the decisions, for a methods section.")
ui.method_link()
st.dataframe(rows, hide_index=True)
