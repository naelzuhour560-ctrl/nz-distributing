# Phase 3: Forecast Baseline

The reference the Week 9 model is measured against. A trailing 4-week mean, backtested on weekly unit demand. Built by `scripts/forecast_prep.py` (dataset) and `scripts/forecast_baseline.py` (backtest). Both are read-only — nothing is written to the DB.

---

## 1. Dataset Construction

**Grain.** One row per `(location_id, store_name, upc, week_start)`, summing `units`. Weeks start Monday (`d - timedelta(days=d.weekday())`).

**Sale-only.** Filtered to `transaction_type = 'Sale'` — 106,867 of the 119,015 invoice rows. Return and Buyback rows net *against* demand rather than describe it, so folding them in would model net shipments, not what the store sold.

**Partial weeks dropped.** The sale date range is 2025-01-01 .. 2026-05-27. 2025-01-01 is a Wednesday, so the first bucket (`2024-12-30`) covers only 5 days, and the last (`2026-05-25`) only 3. Both are real sales but not full selling weeks, and read as artificial dips. The rule is general — drop a boundary week that starts before the first sale date or ends after the last — not a hardcoded pair of dates, so it stays correct when the data is reloaded.

**Zero-fill.** Each series is expanded to one row per week from **its own first sale week** through the end of the grid, with 0 in weeks it did not sell. Weeks before a series' first sale are left absent, not zeroed: no sales there means the product was not yet stocked in that store, which is not the same claim as demand being zero.

| | rows | series | weeks |
|---|---|---|---|
| Raw aggregation | 69,583 | 4,437 | 74 |
| After trim + zero-fill | 232,600 | 4,420 | 72 (2025-01-06 .. 2026-05-18) |

17 series sold only in the dropped boundary weeks and fall out entirely. Post-fill density is **29.4% non-zero** — this is intermittent demand, and that fact drives most of what follows.

---

## 2. Eligibility

A series is scored only if it has **≥12 non-zero weeks strictly before the holdout**. This screens out series too sparse or too new for any mean-based rule to be meaningfully evaluated.

| | series |
|---|---|
| In dataset | 4,420 |
| **Evaluated** | **1,490** |
| Excluded | 2,930 |

Two-thirds of series are excluded. The headline accuracy therefore describes the densest third of the catalogue, not the whole book — the Week 9 model must be scored on this same 1,490 to be comparable.

---

## 3. Holdout

| | |
|---|---|
| Train | 2025-01-06 .. 2026-03-23 (64 weeks) |
| Holdout | 2026-03-30 .. 2026-05-18 (8 weeks) |
| Points | 11,920 (1,490 series × 8 weeks) |
| Non-zero actuals | 5,772 (48.4%) |

---

## 4. Baseline Variants

"Trailing 4-week mean" is ambiguous once the horizon exceeds one week, so both readings are scored:

- **rolling** — one-step-ahead. Each holdout week is predicted from the 4 weeks immediately before it, including earlier holdout actuals. Answers *"how good is this rule if you re-forecast every week?"*
- **static** — computed once from the last 4 training weeks, held flat across all 8 holdout weeks. Answers *"how good is this rule if you forecast the whole horizon up front?"* — the realistic question for an ordering cycle.

Metrics are pooled over all (series, week) points rather than averaged per series, so heavy sellers carry proportionate weight.

| variant | MAPE | **WAPE** |
|---|---|---|
| rolling | 55.6% | **66.1%** |
| static | 54.5% | **66.4%** |

**The two variants land within a point of each other.** Refreshing the forecast weekly with the latest actuals buys essentially nothing, which says the week-to-week variation at this grain is close to noise — there is no short-term signal for a mean to track.

---

## 5. Why WAPE Is the Primary Metric

MAPE is `mean(|actual - forecast| / |actual|)`, which is undefined at `actual = 0` and so is computed only on non-zero actuals. **51.6% of holdout points have zero actual demand** — and those are precisely the points where a trailing mean is guaranteed wrong, since it predicts a positive number into a week with no sale. MAPE discards them by construction and reports on the easier half.

WAPE is `sum|actual - forecast| / sum|actual|` over *all* points. It keeps the zero weeks in the numerator where the error is real, and weights by volume, so a 3-unit miss on a 100-unit week does not count the same as a 3-unit miss on a 4-unit week.

**Score the Week 9 model on WAPE = 66% (static), on the same 1,490 series and the same 8-week holdout.** Report MAPE alongside if useful, but a model that improves MAPE while leaving WAPE flat has most likely just gotten better at the weeks that were already easy.

---

## 6. Implication for Week 9

With 51.6% of holdout points at zero and no detectable short-term signal, this is intermittent demand, where a mean-based forecast is the wrong tool at any window length. The two directions worth trying before tuning window sizes:

- **Croston-type methods**, which model demand size and inter-arrival interval separately rather than averaging through the zeros.
- **A coarser grain** — store × category, or biweekly/monthly buckets — trading resolution for series that are dense enough to forecast.
