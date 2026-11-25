"""Review page: every extracted value with its status, evidence and corrections
(spec 7.11 page 5, 5.6)."""

from typing import get_args

import pandas as pd
import streamlit as st

from exga.app import ui
from exga.messages import guarantee, status
from exga.project import current_thresholds
from exga.schemas import Decision
from exga.views import NOT_CALIBRATED, review_rows, status_css

project = ui.require_project()
store = project.store
settings = ui.settings_for(project)

st.title("Review")
ui.show_flash()
extractions = store.extractions()
if not extractions:
    st.info("Nothing is extracted yet. Upload papers and run the extraction first.")
    ui.link("run")
    st.stop()

specs = {spec.name: spec for spec in store.fields()}
papers = {paper.paper_id: paper for paper in store.papers()}
thresholds = current_thresholds(store)
checked = store.checked_values()

filter_column, field_column = st.columns(2)
decisions: list[Decision] = list(get_args(Decision))
shown_decisions = filter_column.multiselect(
    "Status", decisions, default=decisions, format_func=status
)
shown_fields = field_column.multiselect("Fields", list(specs), default=list(specs))
items = [
    item for item in extractions if item.decision in shown_decisions and item.field in shown_fields
]
for name in shown_fields:
    result = thresholds.get(name)
    st.caption(f"{name}: {NOT_CALIBRATED if result is None else guarantee(result)}")
ui.method_link()
if not items:
    st.info("No values match these filters.")
    st.stop()

table = pd.DataFrame(
    review_rows(items, {pid: paper.filename for pid, paper in papers.items()}, checked)
)
styled = table.style.apply(
    lambda _column: [status_css(item.decision) for item in items], subset=["Status"]
)
event = st.dataframe(
    styled,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="review_table",
    column_config={"Score": st.column_config.NumberColumn(format="%.2f")},
)
selected: list[int] = event["selection"]["rows"]
if not selected or selected[0] >= len(items):  # a selection can outlive a filter change
    st.caption("Select a row to see its evidence and correct it.")
    st.stop()

item = items[selected[0]]
spec = specs[item.field]
paper = papers.get(item.paper_id)
key = (item.paper_id, item.field)
details, evidence = st.columns([2, 3])
with details:
    st.subheader(item.field)
    ui.status_badge(item.decision)
    st.text(f"Paper: {paper.filename if paper else item.paper_id}")
    st.text(f"What was asked: {spec.description}")
    st.text(f"The model's value: {ui.shown_value(item)}")
    if key in checked:
        value = checked[key]
        st.text(f"Checked by a person: {'Not reported' if value is None else value}")
    signals = item.signals
    st.caption(
        f"Confidence score {item.score:.2f}: answers agreed {signals.agreement:.0%}"
        + ("" if signals.logprob is None else f", token probability {signals.logprob:.0%}")
        + ("" if signals.source_match is None else f", evidence check {signals.source_match:.0%}")
    )
    with st.form("correct_value", clear_on_submit=True):
        corrected = st.text_input("Correct value")
        not_reported = st.checkbox("The paper does not report this")
        if st.form_submit_button("Save correction"):
            if not not_reported and not corrected.strip():
                st.error("Enter the value, or tick that the paper does not report it.")
            else:
                store.add_correction(
                    item.paper_id, item.field, None if not_reported else corrected.strip(), ui.now()
                )
                ui.flash("Correction saved.")
                st.rerun()
    st.caption(
        "Corrections appear in this table and the export. They do not change calibration: only "
        "random audits do, because values you chose to check are not a random sample."
    )
with evidence:
    ui.show_evidence(project, item, paper, settings)
