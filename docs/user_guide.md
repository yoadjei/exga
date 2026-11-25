# User guide

This guide walks through the exga app page by page, then lists the settings and what to do
when something goes wrong. Installation and starting the app are in the
[README](../README.md); what the guarantee means is in [method.md](method.md).

## How exga works, in one paragraph

You list the fields you want from each paper. exga asks the model for each field several
times and combines three signals into a confidence score: whether the answers agree, how sure
the model's tokens were, and whether the quoted evidence is really in the paper. Using values
a person has checked, exga then finds, for each field, the lowest score above which wrong
values are rare enough: at most α of the accepted values, with confidence 1 − δ. Values above
that threshold are **Accepted**; the rest are marked **Check**. When a field has too few
checked values, or its errors are too common, it is **Not certifiable** and every value needs
a check.

## Project

A project is a folder. Create one in an empty folder, or open an existing one. The folder
holds `project.sqlite` (fields, answers, checks and the threshold log), `papers/` (a copy of
each PDF, named by its content hash) and `cache/` (model answers, so a rerun costs nothing).
Back up the whole folder to keep a project. The page also shows the next step.

## Fields

Each field has:

- a **name**, used in exports: lower-case letters, digits and underscores, starting with a
  letter;
- a **description**: the question the model answers. It must allow only one right answer
  per paper. "Number of participants randomised, across all groups" works; "sample size"
  does not, because a paper reports several;
- a **group**: `numeric`, `categorical`, `short_text` or `long_text`. The group sets how a
  value is judged right or wrong (ADR 0003), and fields with too few checked values of their
  own are calibrated together with their group;
- for numbers, an optional **unit** and an **absolute** or **relative tolerance**;
- for categories, the **allowed values** and, optionally, synonyms for each.

You can import a whole list as YAML ([examples/fields.yaml](../examples/fields.yaml)) and
download the current one. A field that has extracted values cannot be removed, and once any
values exist an import can no longer replace the list, because checks refer to them; you can
still add fields.

## Upload and run

Add PDFs. A scanned PDF without a text layer is refused, and the page says which one. Then
check the **Endpoint** and **Model**. If the endpoint is not on this computer, exga names the
service that will receive the paper text and waits until you tick that you agree.

**Run extraction** asks the model about every field of every paper that has no answer yet.
The progress bar counts items. If a budget is set and reached, the run stops; the answers so
far are kept, and running again continues where it stopped. Answers come from the cache when
the same question was asked before, at no cost.

## Calibrate

- **Error level.** Choose α: 5%, 10% or 20%. Choose it before looking at results. Changing it
  after seeing which values are accepted weakens the guarantee; the page warns you, and the
  threshold log keeps every change.
- **Fields.** For each field: its status, the threshold, how many checked values it rests
  on, and the guarantee in words. "Pooled" means the field had too few checked values of its
  own and shares its group's, which assumes errors are independent across fields.
- **Checked values needed.** How many accepted checked values certify α with no errors, one
  error or two (also in [method.md](method.md#minimum-calibration-sizes)).
- **Add checked values,** in one of three ways:
  - **Random audit** (recommended). exga draws a random sample of extracted values for you
    to check on the Audit page. Only random samples keep the guarantee valid, which is why
    the Review page's corrections are not used for calibration (ADR 0009).
  - **Checked values for these papers.** A `gold.csv` with the columns `paper_id`, `field`
    and `value`, where `NR` means "not reported". `exga annotation-sheet` writes a blank one.
    These values must not have been chosen by looking at the model's answers.
  - **Records from an experiment.** `records/<model>.jsonl` from an experiment's results
    folder. They certify your papers only if your papers resemble the experiment's and were
    extracted with the same model and prompt; exga cannot check that.
- **Threshold log.** Every recalibration: when it happened, how many checked values it used,
  the error level and how many fields it certified. Claims are about the newest threshold
  only (see [limitations.md](limitations.md)).

## Review

The table lists every value with its status, shown as a symbol, a word and a colour:
**✓ Accepted**, **! Check**, **— Not certifiable**. Filter by field or status. Select a row
to see the paper page with the evidence highlighted, the confidence score and its three
signals, and any value a person gave.

If a value is wrong, type the right one under **Correct value**, or tick **The paper does not
report this**, and press **Save correction**. Corrections go into the export. They do not
change the thresholds, because values chosen for checking are not a random sample. A value
you checked and found right needs no action and leaves no trace.

## Audit

**Start a random audit** on the Calibrate page draws a sample (5% of the extracted values,
at least 3). For each value, look at the paper and answer:

- **✓ The model's value is right**, or
- type the right value (or tick **The paper does not report this**) and press **Save the
  right value**, or
- **I cannot check this item**, if the paper does not let you decide.

**Answer one again** fixes a mistake before the batch is finished. **Finish the audit and
recalibrate** adds the answers as calibration records and recomputes every threshold. Only
one batch can be open at a time.

## Export

**Download results.csv** has one row per paper and field:

| Column | Meaning |
|---|---|
| `paper` | the file name |
| `field` | the field name |
| `value` | the model's value; `NR` if it says the paper does not report the field; empty if it gave no usable answer |
| `decision` | Accepted, Check or Not certifiable |
| `score` | the confidence score, 0 to 1 |
| `evidence` | the passage the model quoted |
| `page` | the first page where the evidence was found |
| `checked_value` | the value a person gave in an audit or a correction; empty if nobody did |

A cell that a spreadsheet could run as a formula starts with an apostrophe.

**Download guarantees.json** records the thresholds and bounds behind the decisions, for a
methods section.

## Settings

Settings come from a `.env` file passed with `--env-file`, or from environment variables of
the same names. The ones you are most likely to set:

| Setting | Default | Meaning |
|---|---|---|
| `EXGA_HOSTED__BASE_URL` | `https://api.openai.com/v1` | the model endpoint; a local server is e.g. `http://localhost:8000/v1` |
| `EXGA_HOSTED__MODEL` | none | the model name; required to run |
| `EXGA_HOSTED__API_KEY` | none | the key; leave unset for a local server that needs none |
| `EXGA_HOSTED__INPUT_PRICE_PER_MILLION`, `EXGA_HOSTED__OUTPUT_PRICE_PER_MILLION` | none | USD per million tokens, for cost accounting |
| `EXGA_HOSTED__BUDGET_USD` | none | stop a run after spending this much; needs both prices |
| `EXGA_HOSTED__REQUESTS_PER_MINUTE` | 60 | request rate limit |
| `EXGA_HOSTED__OUTPUT_TOKENS_PARAM` | `max_tokens` | set to `max_completion_tokens` for newer OpenAI models |
| `EXGA_CALIBRATION__ALPHA` | 0.05 | the error level α before the first calibration |
| `EXGA_CALIBRATION__DELTA` | 0.1 | 1 − δ is the confidence of each field's guarantee |
| `EXGA_EXTRACTION__SAMPLES` | 5 | answers per question; agreement among them is one signal |
| `EXGA_AUDIT__RATE` | 0.05 | share of values drawn by a random audit |

Every setting is in `exga/settings.py`, each with a one-line explanation; an unknown or
invalid setting stops exga with a message naming it.

## When something goes wrong

- **"Not certifiable" for every field.** There are not yet enough checked values. The
  "Checked values needed" table says how many; run random audits until each field has them.
  Some fields stay uncertifiable because the model is wrong too often for α. Try a larger α,
  a clearer field description, or check those fields by hand.
- **A value is empty in the export.** The model gave no usable answer even after repair. The
  item scores 0 and is always marked Check.
- **The run stopped early.** The budget was reached, or the endpoint failed repeatedly. The
  message says which. Run again: finished answers come from the cache.
- **"settings file not found" or a named setting is invalid.** Check the path given to
  `--env-file` and the spelling of the setting in the message.
- **The endpoint refuses the request.** Check the model name. Some models need
  `EXGA_HOSTED__OUTPUT_TOKENS_PARAM=max_completion_tokens`. Models that cannot return token
  log-probabilities need `EXGA_HOSTED__LOGPROBS=false`; the confidence score then uses the
  other two signals.
- **Port 8501 is in use.** Streamlit picks the next free port and prints its address.
