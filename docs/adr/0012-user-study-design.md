# ADR 0012: how the user study compares manual and tool-assisted extraction

- **Status:** accepted 2026-11-25 (the owner delegated this decision)
- **Date:** 2026-11-25
- **Spec:** section 11.3; code: `exga/study.py`, `study/study.py`; materials: `study/`

## Context

Spec 11.3 asks for 5–10 participants, informed consent, anonymous ids and a within-subject
comparison: each person extracts the same fields from two small paper sets, one by hand and
one with exga, in counterbalanced order. Time, accuracy against gold and a short usability
and trust questionnaire are measured and reported descriptively. With so few participants,
every choice that could favour the tool must be fixed before anyone takes part.

## Decisions

1. **Paper sets.** Two sets, A and B, of 3 papers each, taken from the owner's annotated set
   (spec 10.2), so every item has a checked gold value. The fields are the annotated set's
   field list: 6 fields give 18 items per set. Sets are chosen before any session and
   balanced by eye for length and for how many fields are not reported.
2. **Counterbalancing.** Four orders cross which condition comes first with which set it uses
   (manual on A then tool on B, tool on A then manual on B, and the same with the sets
   swapped). Each consecutive block of four participants gets every order once, in a seeded
   random permutation (`study.py prepare --seed`), so a study that stops at 5, 6 or 7 people
   is still close to balanced. The analysis reports every measure for everyone and split by
   which condition came first, so a learning effect is visible.
3. **What the tool condition times.** Before the session the researcher creates one exga
   project per set, uploads its papers, runs the extraction and imports calibration records.
   The participant's clock covers only their own work: reviewing, checking and exporting.
   Model time is a machine cost, reported from the run summary, not from the participant.
4. **No leakage into calibration.** The study projects are calibrated on records from the
   annotated-set experiment **without** the six study papers (`study.py calibration`).
   Otherwise the thresholds would have been set on the very items the participant checks.
5. **Answers and accuracy.** The manual answer is the value written on the sheet; the tool
   answer is the value the participant saved on the Review page, or else the model's value,
   read from exga's own `results.csv` export. An empty answer counts as wrong. The Review
   page records corrections only, so a value checked and found right leaves no trace;
   participants are not asked to retype right values, which would add time to the tool
   condition alone. The study therefore counts **corrections**, not checks. Accuracy is the share of the
   set's 18 gold items answered correctly under each field's correctness rule (spec 6.4),
   the rule the experiments use.
6. **Time limit.** Each condition stops after 25 minutes; unanswered items count as wrong.
   This keeps a session under an hour and treats both conditions the same way.
7. **Questionnaire.** After the tool condition only, since it rates the tool: the System
   Usability Scale (Brooke, 1996) in its standard wording, scored 0–100, and four trust
   statements on the same 1–5 scale. The trust statements are written for this study and are
   not a validated scale, so each is reported on its own (answer counts and median), never
   summed. Two context questions (role; prior experience of data extraction) and two open
   questions complete the form.
8. **Reporting.** Descriptive only, as the spec asks: n, mean, standard deviation, median,
   quartiles and range of time, accuracy, their within-person differences (tool minus manual),
   the share of tool items corrected, and SUS. No hypothesis test: with 5–10 people a p-value
   would mostly reflect the sample size.
9. **Data protection.** Participants are known only by ids P01, P02, … Names appear only on
   signed consent forms, which are kept apart from the data. Forms, answers, papers and
   results stay on the researcher's machine (`study/data/`, `study/papers/` and
   `results/study/` are ignored by git). A participant who withdraws has their rows and files
   deleted; the analysis then leaves them out like anyone with incomplete data and says so.
10. **Ethics approval** is the owner's to obtain from their institution before recruiting.
    The materials have blanks for the approval reference and contact details.

## Consequences

- Results cannot claim the tool is faster or more accurate in general; they describe what
  happened for these participants and papers.
- The tool condition includes the calibration the researcher prepared. If no field is
  certified for the study projects, every value is shown as Check and the study compares
  checking with evidence against extracting from scratch, which the thesis must say.
- Participants see exga once, after a short demonstration; long-term use is not measured.
