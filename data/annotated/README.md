# Owner-annotated set: protocol

This folder documents how the annotated set (spec 10.2) is built. PDFs and gold files are not
committed: `.gitignore` excludes PDFs, and `gold.csv` stays on the owner's machine until it is
released with the thesis data.

## 1. Choose papers

- 50–100 open-access PDFs from varied fields: health, education, social science, computing.
- Text PDFs only. Scanned PDFs are rejected by `exga` and listed as skipped.
- Choose papers before running any model on them, and do not replace a paper because the model
  handles it badly.

## 2. Fix the field list

Use `examples/fields.yaml` or a copy of it. Every description must pin one answer per paper
(spec 6.3). Change the descriptions before labelling starts, never after.

## 3. Make the sheet

```
exga annotation-sheet --papers path/to/pdfs --fields fields.yaml --out data/annotated --seed 0
```

This writes `gold_template.csv` with one row per paper and field. It also marks, with a fixed
seed, 20% of the papers for a second annotator. Record the seed here: ____.

## 4. Label

- Fill the `value` column from the PDF. Write `NR` when the paper does not report the field.
  Never leave a cell empty.
- **Label before looking at any model output.** Seeing the model's answer biases the label
  towards it, which would make the measured error rate too low.
- Numbers as printed, without units. Categories spelt as in `allowed_values`.
- Save as `gold.csv`. The `file` and `double_annotate` columns can stay; they are ignored.

## 5. Second annotator

The second annotator labels only the papers marked `yes`, in a separate copy
(`gold_second.csv`), without seeing the first annotator's values. Then run:

```
exga check-gold --gold gold.csv --fields fields.yaml --second gold_second.csv
```

Report the per-field agreement in the thesis. Resolve each disagreement by discussion and put
the agreed value in `gold.csv`; keep `gold_second.csv` unchanged as the record.

## 6. Check

`exga check-gold --gold gold.csv --fields fields.yaml` must pass before the set is used.
