"""Audit page: check randomly drawn values one at a time (spec 7.11 page 6, 5.6, ADR 0009).

only these random checks become calibration records, so the person sees every drawn item,
accepted or flagged, and may skip one only when it cannot be checked at all.
"""

import streamlit as st

from exga.app import ui
from exga.audit import audit_size
from exga.errors import ConfigError
from exga.messages import percent
from exga.project import draw_next_audit, finish_audit
from exga.store import AuditItem
from exga.views import plain

EDITING = "exga.audit_editing"
"""session key of the (paper, field) being answered again."""

project = ui.require_project()
store = project.store
settings = ui.settings_for(project)

st.title("Audit")
ui.show_flash()
st.write(
    "An audit asks you to check a random sample of all extracted values, accepted and flagged "
    "alike. Only these random checks measure the error rate and certify fields."
)
extractions = {(item.paper_id, item.field): item for item in store.extractions()}
if not extractions:
    st.info("Nothing is extracted yet. Upload papers and run the extraction first.")
    ui.link("run")
    st.stop()

batch = store.open_audit()
if batch is None:
    remaining = len(extractions.keys() - store.audited())
    if remaining == 0:
        st.success("Every extracted value has been audited.")
        st.stop()
    size = audit_size(remaining, settings.audit)
    st.write(
        f"Each batch draws {percent(settings.audit.rate)} of the values not yet audited "
        f"(at least {settings.audit.min_items}): {size} of {remaining} now."
    )
    if st.button(f"Draw {size} values to check", type="primary"):
        draw_next_audit(store, settings, ui.now())
        st.rerun()
    st.stop()

batch_id = batch  # an int from here on; the closure below keeps that type
specs = {spec.name: spec for spec in store.fields()}
papers = {paper.paper_id: paper for paper in store.papers()}
items = store.audit_items(batch_id)
answered = [item for item in items if item.status != "pending"]
st.progress(len(answered) / len(items), text=f"{len(answered)} of {len(items)} answered")

editing = st.session_state.get(EDITING)
pending = [item for item in items if item.status == "pending"]
current = next(
    (item for item in items if (item.paper_id, item.field) == editing),
    pending[0] if pending else None,
)


def _answer(item: AuditItem, checked_value: str | None, *, skipped: bool) -> None:
    store.set_audit_result(
        batch_id,
        item.paper_id,
        item.field,
        checked_value=checked_value,
        skipped=skipped,
        at=ui.now(),
    )
    st.session_state.pop(EDITING, None)
    st.rerun()


if current is not None:
    extraction = extractions[current.paper_id, current.field]
    spec = specs[current.field]
    paper = papers.get(current.paper_id)
    details, evidence = st.columns([2, 3])
    with details:
        st.subheader(f"Item {items.index(current) + 1} of {len(items)}")
        st.text(f"Paper: {paper.filename if paper else current.paper_id}")
        st.text(f"Field: {spec.name}, {spec.description}")
        st.text(f"The model's value: {ui.shown_value(extraction)}")
        st.caption("Check the value against the paper, then answer.")
        if extraction.failed:
            st.caption("The model gave no usable answer, so enter the right value below.")
        elif st.button("✓ The model's value is right", type="primary"):
            _answer(current, extraction.value, skipped=False)
        with st.form("right_value", clear_on_submit=True):
            right = st.text_input("✗ It is wrong. The right value is:")
            not_reported = st.checkbox("The paper does not report this")
            if st.form_submit_button("Save the right value"):
                if not not_reported and not right.strip():
                    st.error("Enter the value, or tick that the paper does not report it.")
                else:
                    _answer(current, None if not_reported else right.strip(), skipped=False)
        if st.button("I cannot check this item"):
            _answer(current, None, skipped=True)
        st.caption(
            "Skip only an item that cannot be checked at all, such as an unreadable paper. "
            "Skips are counted, and skipping hard items would make the error rate look better "
            "than it is."
        )
    with evidence:
        ui.show_evidence(project, extraction, paper, settings)
else:
    skipped = sum(item.status == "skipped" for item in items)
    st.success(
        f"All {len(items)} items are answered"
        + (f", {skipped} of them skipped." if skipped else ".")
    )
    if st.button("Finish the audit and recalibrate", type="primary"):
        try:
            version = finish_audit(store, batch_id, settings, ui.now())
        except ConfigError as exc:
            st.error(plain(str(exc)))
        else:
            certified = sum(result.certified for result in version.results.values())
            ui.flash(
                f"Audit finished: {len(items) - skipped} checked values added. "
                f"{certified} of {len(version.results)} fields are certified."
            )
            st.rerun()

if answered:
    with st.expander("Your answers in this batch"):
        st.dataframe(
            [
                {
                    "Paper": papers[item.paper_id].filename if item.paper_id in papers else "",
                    "Field": item.field,
                    "Answer": (
                        "Skipped"
                        if item.status == "skipped"
                        else ("Not reported" if item.checked_value is None else item.checked_value)
                    ),
                }
                for item in answered
            ],
            hide_index=True,
        )
        labels = {
            f"{index + 1}. {item.field} in "
            f"{papers[item.paper_id].filename if item.paper_id in papers else item.paper_id}": item
            for index, item in enumerate(answered)
        }
        again = st.selectbox("Answer one again", list(labels))
        if st.button("Answer again") and again is not None:
            st.session_state[EDITING] = (labels[again].paper_id, labels[again].field)
            st.rerun()
