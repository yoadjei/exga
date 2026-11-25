# User study: researcher's guide

This folder holds what the researcher needs to run the user study of spec 11.3. The design
and the reasons for it are in [ADR 0012](../docs/adr/0012-user-study-design.md).

| File | For | Use |
|---|---|---|
| [consent.md](consent.md) | participant | information sheet and consent form; fill the blanks first |
| [task_sheet.md](task_sheet.md) | participant | instructions, read aloud before each task |
| [questionnaire.md](questionnaire.md) | participant | after the tool task |
| `study.py` | researcher | forms, sheets, calibration records and the analysis |

Participant data never leaves this computer: `study/data/`, `study/papers/` and
`results/study/` are ignored by git. Names appear only on signed consent forms, which are
kept apart from the data.

## 1. Before recruiting

1. Get ethics approval from your institution. Reference: ____.
2. Fill the blanks in `consent.md`: researcher, supervisor, contact details, approval
   reference, the last date for withdrawal and how long data are kept.
3. Recruit 5–10 students or researchers. Plan for 8: the order of tasks is balanced in
   blocks of four.

## 2. Prepare once

1. **Choose the papers** before any session, from the annotated set (`data/annotated`), so
   every item has a checked gold value. Put 3 PDFs in `study/papers/A` and 3 in
   `study/papers/B`. Balance the sets by eye for length and for how many fields are not
   reported. Keep one more annotated paper, in neither set, for training.
2. **Calibration records without the study papers.** Run the annotated experiment (PROGRESS,
   owner action 4), then:

   ```
   python study/study.py calibration --records results/annotated-<hash>/records/hosted.jsonl
   ```

   This writes `study/data/calibration.jsonl`, the annotated records minus those of the six
   study papers.
3. **One clean project per set.** With the same model settings as the annotated experiment,
   run `exga app`, create a project in an empty folder (for example `study/projects/A-clean`)
   with the fields of `data/annotated/fields.yaml`, upload set A, run the extraction, and on
   the Calibrate page import `study/data/calibration.jsonl`. Repeat for set B. Before each
   session, copy the clean project folder (for example to `study/projects/P01-tool`); a
   participant's corrections are saved in the project, so never reuse one.
4. **Forms:**

   ```
   python study/study.py prepare --participants 8 --seed 0
   python study/study.py sheet --papers study/papers/A --out study/data/sheet_A.csv
   python study/study.py sheet --papers study/papers/B --out study/data/sheet_B.csv
   ```

   `assignment.csv` says, for each participant id, which task comes first and on which set.
   Record the seed here: ____.
5. **Pilot** the whole session with one person who is not a participant. Fix unclear wording
   in the materials then; after the first participant, change nothing.

## 3. Each session (about 60 minutes)

| Step | Minutes | What happens |
|---|---|---|
| Welcome and consent | 5 | Give `consent.md`; answer questions; both sign. Assign the next free id. |
| Training | 10 | Read `task_sheet.md` aloud. On the training paper, show both ways: filling the sheet, and exga's Review page (statuses, evidence, Save correction, Export). Same demonstration for everyone. |
| First task | up to 25 | As `assignment.csv` says. Start the clock when the participant starts; stop it when they say they are done, or at 25 minutes. |
| Break | 2 | |
| Second task | up to 25 | The other condition, on the other set. |
| Questionnaire | 5 | `questionnaire.md`. |
| Debrief | 3 | Thank them; say when results will be available. |

- **Manual task:** give the set's PDFs and a copy of `sheet_<set>.csv`. Save the filled sheet
  as `study/data/answers/<id>_manual.csv`.
- **Tool task:** open the participant's copy of the set's project with `exga app`, on the
  Review page. When they are done, they export `results.csv` on the Export page. Save it as
  `study/data/answers/<id>_tool.csv`. Participants do not use the Audit page.
- **Times** go into `study/data/sessions.csv` in minutes, with decimals (for example 18.5).
- **Questionnaire answers** go into `study/data/questionnaire.csv`. Open answers stay on the
  paper form; quote them only if the participant agreed on the consent form.

## 4. Analyse

```
python study/study.py analyse
```

This reads the forms and answers, scores each participant against `data/annotated/gold.csv`
and writes to `results/study/`:

- `participants.csv`: one row per participant who finished, with time and accuracy per
  condition, their differences (tool minus manual), corrections made with the tool, and SUS.
- `summary.csv`: for each measure, n, mean, standard deviation, median, quartiles and range,
  for everyone and split by which task came first.
- `trust.csv`: for each trust statement, how many people gave each answer, and the median.
- `manifest.json`: the git commit, the settings and a hash of every input file, and who was
  left out and why.

Participants with a missing time, answer file or questionnaire are left out and listed. Report
the study descriptively (ADR 0012): no hypothesis tests, and no claims beyond these
participants and papers.

## 5. If someone withdraws

Delete their rows from `sessions.csv` and `questionnaire.csv`, their answer files and their
paper questionnaire. Keep their line in `assignment.csv`, which holds no personal data, so
the order of later participants stays as planned. The analysis then lists them as left out.
