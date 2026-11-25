"""the app's entry point: `exga app` runs `streamlit run` on this file (ADR 0010).

pages are listed in the order of the workflow: set up, extract, calibrate, then review,
audit and export.
"""

import streamlit as st

from exga.app import ui

st.set_page_config(page_title="exga", layout="wide")
ui.base_settings()  # stops every page at once when the settings are invalid


def _page(screen: str) -> st.Page:
    return st.Page(ui.SCREENS[screen], title=ui.TITLES[screen], default=screen == "project")


pages = {
    "Set up": [_page("project"), _page("fields")],
}

with st.sidebar:
    project = ui.current_project()
    if project is None:
        st.caption("No project open")
    else:
        st.caption("Project")
        st.text(project.root.name)
    ui.method_link()

st.navigation(pages).run()
