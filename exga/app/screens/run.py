"""Upload and run page: add papers, choose the model, extract (spec 7.11 page 3, 0A.5)."""

from urllib.parse import urlsplit

import streamlit as st

from exga.app import ui
from exga.errors import BudgetExceededError, ConfigError, PdfParseError
from exga.llm.hosted import HostedLLMClient, endpoint_is_local
from exga.messages import percent
from exga.project import add_paper_file, run_extraction
from exga.views import paper_rows, plain

project = ui.require_project()
store = project.store
settings = ui.settings_for(project)

st.title("Upload and run")
ui.show_flash()

st.subheader("Papers")
with st.form("upload_papers", clear_on_submit=True):
    uploads = st.file_uploader(
        "PDFs, or .md / .txt text files", type=["pdf", "md", "txt"], accept_multiple_files=True
    )
    if st.form_submit_button("Add papers"):
        added, problems = 0, []
        for upload in uploads or []:
            try:
                add_paper_file(project, upload.name, upload.getvalue(), settings.document, ui.now())
            except PdfParseError as exc:
                problems.append(str(exc))
            else:
                added += 1
        if added:
            st.success(f"Added {added} paper{'' if added == 1 else 's'}.")
        for problem in problems:
            st.error(plain(problem))

papers = store.papers()
specs = store.fields()
extractions = store.extractions()
if papers:
    st.dataframe(paper_rows(papers, extractions, len(specs)), hide_index=True)
else:
    st.info("No papers yet. Add PDFs above; scanned PDFs without a text layer are not supported.")

st.subheader("Model")
hosted = settings.hosted
base_url = st.text_input(
    "Endpoint",
    value=hosted.base_url,
    help="Any OpenAI-compatible chat-completions API, hosted or a local vLLM or llama.cpp server.",
)
model = st.text_input("Model", value=hosted.model or "")
st.caption(
    "An API key, if the endpoint needs one, is read from the EXGA_HOSTED__API_KEY environment "
    "variable. It is never shown or stored by exga."
)
valid_url = urlsplit(base_url).scheme in {"http", "https"} and bool(urlsplit(base_url).hostname)
if not valid_url:
    st.error("The endpoint must be an http:// or https:// address.")
consent = True
if valid_url and endpoint_is_local(base_url):
    st.info("This endpoint runs on this computer: paper text stays on this machine.")
elif valid_url:
    st.warning(
        "This endpoint is not on this computer. The full text of every paper is sent to "
        f"{plain(urlsplit(base_url).hostname or '')} to extract values, under that provider's "
        "terms."
    )
    consent = st.checkbox("I agree to send the text of these papers to this service.")

pending = len(papers) * len(specs) - len(extractions)
st.subheader("Run")
if not specs:
    st.info("Add fields before running.")
    ui.link("fields")
elif not papers:
    st.info("Add papers before running.")
elif pending <= 0:
    st.success("Every field of every paper is extracted.")
    ui.link("calibrate")
else:
    st.write(
        f"{pending} item{'' if pending == 1 else 's'} to extract. For each, the model gives one "
        f"answer and {settings.extraction.samples} more sampled ones, used to score confidence."
    )
run_settings = settings.model_copy(
    update={
        "hosted": hosted.model_copy(update={"base_url": base_url, "model": model.strip() or None})
    }
)
ready = bool(specs and papers and pending > 0 and valid_url and consent and model.strip())
if not model.strip():
    st.caption("Enter a model name to run.")
if st.button("Run extraction", type="primary", disabled=not ready):
    bar = st.progress(0.0, text="Starting…")

    def progress(done: int, total: int) -> None:
        """move the bar as items finish; called on this thread."""
        bar.progress(done / total, text=f"{done} of {total} items")

    try:
        with ui.model_client(run_settings) as client:
            summary = run_extraction(project, client, run_settings, ui.now(), progress)
            usage = client.meter.summary() if isinstance(client, HostedLLMClient) else None
    except BudgetExceededError as exc:
        st.warning(f"Stopped: {plain(str(exc))}. Answers so far are cached; run again to continue.")
    except ConfigError as exc:
        st.error(f"The model cannot be used: {plain(str(exc))}")
    else:
        bar.progress(1.0, text="Done")
        st.success(f"Extracted {summary.extracted} item{'' if summary.extracted == 1 else 's'}.")
        if summary.parse_failure_rate is not None:
            st.caption(
                f"Answers the model could not format, even after one repair: "
                f"{percent(summary.parse_failure_rate)}."
            )
        if summary.failed_requests:
            st.warning(
                f"{summary.failed_requests} item(s) failed and will be retried on the next run."
            )
            with st.expander("What failed"):
                for line in summary.errors:
                    st.text(line)
        for skipped in summary.skipped:
            st.warning(plain(f"Skipped {skipped.filename}: {skipped.reason}"))
        if usage is not None:
            cost = usage["cost_usd"]
            st.caption(
                f"{usage['requests']} requests · {usage['input_tokens']:,} tokens in · "
                f"{usage['output_tokens']:,} tokens out"
                + ("" if cost is None else f" · {cost:.2f} USD")
            )
        ui.link("review")
