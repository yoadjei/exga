"""Fields page: the values to extract from every paper (spec 7.11 page 2)."""

from typing import get_args

import streamlit as st

from exga.app import ui
from exga.errors import ConfigError
from exga.fields import fields_to_yaml, load_fields, parse_field
from exga.schemas import FieldGroup
from exga.views import field_rows, plain

GROUP_HELP = {
    "numeric": "a number, such as a sample size; tolerances set how close counts as right",
    "categorical": "one of a fixed list of values, such as the study design",
    "short_text": "a short phrase, such as a country",
    "long_text": "a sentence or more, such as the main outcome",
}

project = ui.require_project()
store = project.store
specs = list(store.fields())
in_use = {extraction.field for extraction in store.extractions()}

st.title("Fields")
ui.show_flash()
st.write("Each field is one value the model looks for in every paper.")
if specs:
    st.dataframe(field_rows(specs), hide_index=True)
    st.download_button(
        "Download fields.yaml", fields_to_yaml(specs), file_name="fields.yaml", mime="text/yaml"
    )
else:
    st.info("No fields yet. Add the first one below, or import a field list.")

st.subheader("Add a field")
group = st.selectbox(
    "Kind of value",
    get_args(FieldGroup),
    format_func=lambda name: f"{name.replace('_', ' ')}: {GROUP_HELP[name]}",
)
with st.form("add_field", clear_on_submit=True):
    name = st.text_input("Name", help="lower case letters, digits and _, e.g. sample_size")
    description = st.text_area("What to extract", help="this text is shown to the model")
    entry: dict[str, object] = {"name": name, "description": description, "group": group}
    if group == "categorical":
        allowed = st.text_area("Allowed values, one per line")
        entry["allowed_values"] = [line.strip() for line in allowed.splitlines() if line.strip()]
    if group == "numeric":
        unit = st.text_input("Unit (optional)", help="e.g. kg or years")
        absolute = st.number_input("Absolute tolerance", min_value=0.0, value=0.0)
        relative = st.number_input("Relative tolerance (%)", min_value=0.0, value=0.0)
        entry.update(
            {
                "unit": unit.strip() or None,
                "numeric_tolerance": absolute,
                "rel_tolerance": relative / 100,
            }
        )
    if st.form_submit_button("Add field"):
        try:
            spec = parse_field(entry)
        except ConfigError as exc:
            st.error(f"The field cannot be added: {plain(str(exc))}")
        else:
            if spec.name in {existing.name for existing in specs}:
                st.error(f"A field named {spec.name} already exists.")
            else:
                store.save_fields([*specs, spec])
                ui.flash(f"Added {spec.name}. The next run extracts it from every paper.")
                st.rerun()

removable = [spec.name for spec in specs if spec.name not in in_use]
if specs:
    st.subheader("Remove a field")
    if not removable:
        st.caption("Every field has extracted values, so none can be removed.")
    else:
        with st.form("remove_field"):
            target = st.selectbox("Field", removable)
            confirmed = st.checkbox("Yes, remove this field")
            if st.form_submit_button("Remove"):
                if not confirmed:
                    st.error("Tick the box to confirm.")
                else:
                    store.save_fields([spec for spec in specs if spec.name != target])
                    ui.flash(f"Removed {target}.")
                    st.rerun()
        st.caption("Fields with extracted values cannot be removed: their checks refer to them.")

st.subheader("Import a field list")
if in_use:
    st.caption("Values have been extracted, so the field list can only grow; add fields above.")
else:
    with st.form("import_fields"):
        upload = st.file_uploader("fields.yaml", type=["yaml", "yml"])
        if st.form_submit_button("Replace the field list") and upload is not None:
            try:
                with ui.uploaded_file(upload) as path:
                    imported = load_fields(path)
            except ConfigError as exc:
                st.error(plain(str(exc)))
            else:
                store.save_fields(imported)
                ui.flash(f"Imported {len(imported)} fields.")
                st.rerun()
