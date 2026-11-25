"""Project page: open or create a project folder, and see what to do next (spec 7.11 page 1)."""

from pathlib import Path

import streamlit as st

from exga.app import ui
from exga.errors import ConfigError
from exga.project import create_project, open_project
from exga.views import next_step, plain

st.title("Project")
ui.show_flash()


def _folder(text: str) -> Path | None:
    if not text.strip():
        st.error("Enter a folder.")
        return None
    return Path(text.strip()).expanduser()


project = ui.current_project()
if project is None:
    st.write(
        "A project is one folder that holds its papers, results and checked values. "
        "Nothing leaves this computer except paper text sent to the model you choose on the "
        "Upload and run page."
    )
    open_column, new_column = st.columns(2)
    with open_column, st.form("open_project"):
        st.subheader("Open a project")
        existing = st.text_input("Project folder", key="open_folder")
        if st.form_submit_button("Open") and (folder := _folder(existing)) is not None:
            try:
                open_project(folder)
            except ConfigError as exc:
                st.error(plain(str(exc)))
            else:
                st.session_state[ui.PROJECT_ROOT] = str(folder)
                st.rerun()
    with new_column, st.form("new_project"):
        st.subheader("Create a project")
        new = st.text_input("New or empty folder", key="new_folder")
        if st.form_submit_button("Create") and (folder := _folder(new)) is not None:
            try:
                create_project(folder, [])
            except (ConfigError, OSError) as exc:
                st.error(plain(str(exc)))
            else:
                st.session_state[ui.PROJECT_ROOT] = str(folder)
                ui.flash("Project created. Add the fields to extract next.")
                st.rerun()
    st.stop()

store = project.store
specs = store.fields()
papers = store.papers()
extractions = store.extractions()
records = store.records()
st.text(f"Folder: {project.root}")
columns = st.columns(4)
columns[0].metric("Fields", len(specs))
columns[1].metric("Papers", len(papers))
columns[2].metric("Extracted values", len(extractions))
columns[3].metric("Checked values", len(records))
if store.open_audit() is not None:
    st.info("An audit batch is open. Finish it on the Audit page before drawing another.")
message, screen = next_step(
    fields=len(specs), papers=len(papers), extracted=len(extractions), records=len(records)
)
st.subheader("Next step")
st.write(message)
ui.link(screen)
if st.button("Close project"):
    del st.session_state[ui.PROJECT_ROOT]
    st.rerun()
