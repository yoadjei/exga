# ADR 0010: a local Streamlit app over the library, and its limits

- **Status:** accepted 2026-11-25 (the owner delegated this decision)
- **Date:** 2026-11-25
- **Spec:** sections 0A.6, 7.11; code: `app/`, `exga/project.py`

## Context

The owner and study participants need six screens: Fields, Run, Calibrate, Review, Audit and
Export. The tool runs on one person's laptop and opens one project at a time. The thesis is
about the method, so the interface should cost as little code as possible while meeting the
standards in spec 0A.6.

## Options

| Option | For | Against | Verdict |
|---|---|---|---|
| **Streamlit** | named in the spec; pure Python; tables, forms and images built in; `AppTest` runs pages headlessly in CI | the whole script reruns on every interaction; limited layout and focus control; state lives in `st.session_state` | **chosen** |
| FastAPI with HTMX templates | full control of markup and accessibility | about three times the code: routes, templates, CSS; a second language in the repository | rejected for scope |
| Gradio, NiceGUI | quick forms | weaker multi-page structure; less known to examiners | rejected |

## Decision

- The pages live in `exga/app/`, not the top-level `app/` that spec section 8 sketches, and
  are ordered with `st.navigation` rather than numbered file names. Inside the package they
  ship in the wheel, so `exga app` finds them after `pip install`; `1_Fields.py` is not a
  valid module name, so mypy could not check numbered pages.
- The pages hold only page code. Every action calls `exga.project`, which the CLI also uses,
  and every table comes from `exga.views`, so the method is implemented once and tested
  without the UI.
- A project is a folder holding `project.sqlite`, the uploaded `papers/` (named by their
  sha256) and the model response `cache/`. One folder per project; no server, no accounts.
- Status is shown as a symbol, a word and a colour together ("✓ Accepted", "! Check",
  "— Not certifiable"), never colour alone. Guarantees use `exga.messages`, so the app states
  exactly what was certified, "for this field".
- Before any request to a hosted model, the Run page states which endpoint receives the paper
  text, and a non-loopback endpoint needs explicit consent (spec 0A.5).
- `exga app` starts Streamlit with `--server.address=localhost` and
  `--browser.gatherUsageStats=false`. Streamlit's defaults listen on every network interface,
  so anyone on the same network could open the project's papers, look up the machine's public
  address through an outside service, and send usage statistics. Verified on 2026-11-25: with
  the defaults the server printed a Network and an External URL; bound to localhost, a
  connection to the LAN address was refused.
- `exga app` also hides Streamlit's Deploy button (`--client.toolbarMode=minimal`), which
  invites publishing the app, papers included, to a cloud, and sets a blue accent
  (`--theme.primaryColor=#2563eb`) so selected "Accepted" chips are not red. A custom accent
  puts Streamlit in its light theme, which the status colours (dark text on light
  backgrounds) were designed for. A real-browser pass on 2026-11-25 confirmed all three.
- Text that comes from papers or the model is shown with `st.text` or in tables, and messages
  that quote names pass through `exga.views.plain`, so a paper or file name cannot inject a
  link or a remote image into the page.

## Known limits

- **Reruns.** A long extraction blocks the page while it runs, with a progress bar. Closing
  the tab stops it; the response cache makes a rerun resume where it stopped.
- **One user at a time.** Several tabs share the project database safely (each call opens its
  own connection, WAL mode), but there is no locking of audit items between people.
- **Accessibility.** Streamlit's widgets are keyboard-usable, and the colours chosen meet WCAG
  AA contrast, but focus order and screen-reader labels of its data editor cannot be
  controlled. The Review table therefore repeats each status in words.
- **No undo.** Calibration records cannot be deleted at all (ADR 0009). The one destructive
  action, starting a new project in a folder that already holds one, is refused.
