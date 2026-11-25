"""Calibrate page: set the error level, add checked values, see what each field can promise
(spec 7.11 page 4, 5.4a, 5.6)."""

import streamlit as st

from exga.app import ui
from exga.errors import ConfigError
from exga.messages import not_certifiable_warning, percent
from exga.project import (
    current_thresholds,
    draw_next_audit,
    import_gold_file,
    import_record_file,
    recalibrate_project,
)
from exga.views import DISPLAY_ALPHAS, field_status_rows, plain, required_n_rows

project = ui.require_project()
store = project.store
settings = ui.settings_for(project)
specs = store.fields()
calibration = settings.calibration
confidence = percent(1 - calibration.delta)

st.title("Calibrate")
ui.show_flash()
st.write(
    "A field is certified when enough values checked by people show that, among the values "
    "exga accepts, at most the chosen share is wrong, at "
    f"{confidence} confidence. Values below the field's threshold are flagged for checking."
)
ui.method_link()
if not specs:
    st.info("Add fields first.")
    ui.link("fields")
    st.stop()

st.subheader("Error level")
options = sorted({*DISPLAY_ALPHAS, calibration.alpha})
alpha = st.selectbox(
    "Most wrong values you accept among accepted ones",
    options,
    index=options.index(calibration.alpha),
    format_func=lambda value: f"≤ {percent(value)}",
)
if alpha != calibration.alpha:
    st.warning(
        "Choose the error level before you look at results. Changing it after seeing which "
        "fields certify weakens the guarantee. Every change is kept in the threshold log."
    )
    if st.button(f"Recalibrate at ≤ {percent(alpha)}"):
        chosen = settings.model_copy(
            update={"calibration": calibration.model_copy(update={"alpha": alpha})}
        )
        version = recalibrate_project(store, chosen, ui.now())
        ui.flash(f"Recalibrated at ≤ {percent(alpha)} (threshold version {version.version}).")
        st.rerun()

st.subheader("Fields")
thresholds = current_thresholds(store)
st.dataframe(field_status_rows(specs, thresholds, store.records()), hide_index=True)
for spec in specs:
    result = thresholds.get(spec.name)
    if result is not None and not result.certified:
        st.warning(f"{spec.name}: {not_certifiable_warning(result)}")

st.subheader("Checked values needed")
st.write(
    f"Fewest accepted checked values that can certify each level at {confidence} confidence. "
    "A field with fewer of its own is pooled with the other fields of its kind, or stays not "
    "certifiable."
)
st.dataframe(required_n_rows(calibration.delta), hide_index=True)

st.subheader("Add checked values")
audit_column, gold_column, records_column = st.columns(3)
with audit_column:
    st.markdown("**Random audit** (recommended)")
    st.caption(
        "Check a random sample of the extracted values. Only random samples measure the "
        "error rate without bias."
    )
    if st.button("Start a random audit"):
        if draw_next_audit(store, settings, ui.now()) is None:
            st.error("Every extracted value has been audited, or none are extracted yet.")
        else:
            st.switch_page(ui.SCREENS["audit"])
with gold_column, st.form("import_gold", clear_on_submit=True):
    st.markdown("**Checked values for these papers**")
    st.caption(
        "gold.csv with columns paper_id, field, value (NR = not reported). Use values checked "
        "for a random sample of papers, not ones picked because they looked wrong."
    )
    gold = st.file_uploader("gold.csv", type=["csv"])
    if st.form_submit_button("Import") and gold is not None:
        try:
            with ui.uploaded_file(gold) as path:
                version = import_gold_file(project, path, settings, ui.now())
        except ConfigError as exc:
            st.error(plain(str(exc)))
        else:
            ui.flash(f"Imported checked values (threshold version {version.version}).")
            st.rerun()
with records_column, st.form("import_records", clear_on_submit=True):
    st.markdown("**Records from an experiment**")
    st.caption(
        "records/<model>.jsonl from an experiment's results folder. They certify your papers "
        "only if your papers resemble the experiment's and were extracted with the same model "
        "and prompt."
    )
    records_file = st.file_uploader("records.jsonl", type=["jsonl"])
    if st.form_submit_button("Import") and records_file is not None:
        try:
            with ui.uploaded_file(records_file) as path:
                version = import_record_file(project, path, settings, ui.now())
        except ConfigError as exc:
            st.error(plain(str(exc)))
        else:
            ui.flash(f"Imported records (threshold version {version.version}).")
            st.rerun()

log = store.threshold_log()
if log:
    with st.expander(f"Threshold log ({len(log)} versions)"):
        st.dataframe(
            [
                {
                    "Version": entry.version,
                    "When (UTC)": entry.created_at.strftime("%Y-%m-%d %H:%M"),
                    "Checked values": entry.n_records,
                    "Error level": ", ".join(
                        sorted({f"≤ {percent(r.alpha)}" for r in entry.results.values()})
                    ),
                    "Certified fields": sum(r.certified for r in entry.results.values()),
                }
                for entry in reversed(log)
            ],
            hide_index=True,
        )
