# ADR 0008: how the Yun et al. benchmark becomes exga items

- **Status:** accepted 2026-11-25 (the owner delegated this decision)
- **Date:** 2026-11-25
- **Spec:** sections 5.4, 10.1, 10.3; code: `exga/benchmark.py`, `scripts/download_benchmark.py`

## Context

Yun et al. (2024) annotated 699 intervention–comparator–outcome triplets in 120 RCT reports.
The data are Apache-2.0, pinned here to commit `1bc768d4`. Each triplet has up to eight numbers:
event counts and group sizes for binary outcomes, and means, standard deviations and group sizes
for continuous ones. The text of each report is a markdown file with the abstract and results;
figures are placeholders. exga's unit is one field of one paper, with a single correct answer,
and items must be independent across papers (spec 5.4). The raw data, inspected on
2026-11-25, show several mismatches with that unit:

- A paper has 1 to 29 triplets (mean 5.8), so one field has several items per paper.
- A blank cell means "no usable number". The notes give reasons: not reported, given only as a
  median or range, or a difference between groups.
- 179 triplets are flagged as having their data in figures or in tables stored as images.
  166 of them have values filled in, which the text input cannot contain.
- Some values were calculated by annotators, for example events from percentages.

## Decisions

1. **Fields.** Eight numeric fields named after the columns, such as `intervention_events`.
   Events apply only to binary outcomes; means and SDs only to continuous ones; group sizes to
   both. A field that does not apply gives no item.
2. **Questions.** Each item's description names its triplet, from the versioned templates in
   `exga/prompts/benchmark_fields_v1.yaml`. Example: "mean of the outcome "duration of the
   illness" in the White Grape Juice group".
3. **Gold.** A filled cell is the gold value; thousands separators are allowed. A blank cell of
   a field that applies is "not reported": the text gives no usable number. Values the
   annotators calculated stay as gold. A model that does the same arithmetic is right; one that
   does not is wrong.
4. **Exclusions.** Triplets flagged `is_data_in_figure_graphics` or `is_table_in_graphic_format`
   are left out, because their gold values are not in the text the model reads.
5. **Independence.** For each field, each paper contributes one triplet. It is chosen at random
   among that paper's eligible triplets, with a seed derived from (seed, paper, field) so the
   choice does not depend on data order. (paper, field) stays the calibration unit, as in spec
   5.4. Using every triplet is a secondary analysis that must report the clustering check
   (spec 5.4, 7.8).
6. **Splits.** The 10 DEV papers are used only to develop prompts and never enter calibration or
   test. The 110 TEST papers are split by paper into 30% score-model training, 40% calibration
   and 30% test (spec 10.3), repeated over 50 seeds in experiments.
7. **Matching.** Numeric equality after parsing, with zero tolerance. A rounding difference
   counts as an error, which is the strict reading.

## Consequences

- Per field, the test split has at most about 33 papers and calibration at most about 44. At
  α = 0.10 and δ = 0.1, certification needs at least 22 accepted items with no errors (spec
  5.4a), so some benchmark fields will be not certifiable. That is a result to report, not a
  defect.
- Excluding graphics-flagged triplets removes 167 of the 656 TEST triplets. The remaining items
  are the ones a text-only extractor could get right.
- Gold values the annotators calculated make some items harder than pure extraction. The thesis
  should report how many items fall in each case.
