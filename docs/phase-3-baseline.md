# Phase 3: Forecast Baseline and Week 9 Result

The trailing-mean baseline, the model measured against it, and the acceptance rule for anything that follows. Built by `scripts/forecast_prep.py` (dataset), `scripts/forecast_baseline.py` (baseline), and `scripts/forecast_model.py` (model, and `--write` to publish).

**Current figures are the August 2026 export** (139,102 invoice rows, of which 124,472 are Sales). They replace the May 2026 numbers this document previously carried; §11 records what changed.

**Result in one line:** tweedie 1.7 single-stage XGBoost at **60.0% WAPE / 0.7% missed units**, against a baseline of **64.4% / 2.5%**. Better on both metrics, and 7 points short of the original ≤53% target — which §8 argues is not reachable at this grain.

---

## 1. Dataset Construction

**Grain.** One row per `(location_id, store_name, upc, week_start)`, summing `units`. Weeks start Monday (`d - timedelta(days=d.weekday())`).

**Sale-only.** Filtered to `transaction_type = 'Sale'` — 124,472 of the 139,102 invoice rows. Return and Buyback rows net *against* demand rather than describe it, so folding them in would model net shipments, not what the store sold.

**Partial weeks dropped.** The sale date range is 2025-01-01 .. 2026-08-17. 2025-01-01 is a Wednesday, so the first bucket (`2024-12-30`) covers only 5 days, and the last (`2026-08-17`) only 1. Both are real sales but not full selling weeks, and read as artificial dips. The rule is general — drop a boundary week that starts before the first sale date or ends after the last — not a hardcoded pair of dates, so it stays correct as the data is reloaded.

**Zero-fill.** Each series is expanded to one row per week from **its own first sale week** through the end of the grid, with 0 in weeks it did not sell. Weeks before a series' first sale are left absent, not zeroed: no sales there means the product was not yet stocked in that store, which is not the same claim as demand being zero.

| | rows | series | weeks |
|---|---|---|---|
| Raw aggregation | 80,745 | 4,665 | 86 |
| After trim + zero-fill | 288,489 | 4,660 | 84 (2025-01-06 .. 2026-08-10) |

5 series sold only in the dropped boundary weeks and fall out entirely. Post-fill density is **27.7% non-zero** — this is intermittent demand, and that fact drives everything below.

---

## 2. Eligibility

A series is scored only if it has **≥12 non-zero weeks strictly before the holdout**. This screens out series too sparse or too new to evaluate meaningfully.

| | series |
|---|---|
| In dataset | 4,660 |
| **Evaluated** | **1,685** |
| Excluded | 2,975 |

Two-thirds of series are excluded. Every accuracy number here therefore describes the densest third of the catalogue, not the whole book. **Any model compared against these figures must be scored on the same 1,685 series.**

The model *trains* on all 4,660 series — a sparse series still carries signal about how demand behaves — but is *evaluated* only on the eligible 1,685.

---

## 3. Holdout

| | |
|---|---|
| Train | 2025-01-06 .. 2026-06-15 (76 weeks) |
| Holdout | 2026-06-22 .. 2026-08-10 (8 weeks) |
| Points | 13,480 (1,685 series × 8 weeks) |
| Non-zero actuals | 6,209 (46.1%) |
| Total actual units | 113,660 |

**53.9% of holdout points are zero.** That single fact explains most of what follows.

---

## 4. Baseline

"Trailing 4-week mean" is ambiguous once the horizon exceeds one week, so both readings are scored:

- **rolling** — one-step-ahead. Each holdout week is predicted from the 4 weeks immediately before it, including earlier holdout actuals. Answers *"how good is this rule if you re-forecast every week?"*
- **static** — computed once from the last 4 training weeks, held flat across all 8 holdout weeks. Answers *"how good is this rule if you forecast the whole horizon up front?"* — the realistic question for an ordering cycle, and the reference figure.

| variant | MAPE | **WAPE** | missed units |
|---|---|---|---|
| rolling | 56.1% | **62.1%** | 3.1% |
| static | 55.6% | **64.4%** | 2.5% |

On the May data these two were within 0.3 points of each other. They are now 2.3 points apart, with rolling ahead — with 84 weeks instead of 72, re-forecasting weekly has started to pay. Static remains the reference, since it matches how an ordering cycle actually consumes a forecast.

---

## 5. Metrics: the Two-Metric Rule

Metrics are pooled over all (series, week) points rather than averaged per series, so heavy sellers carry proportionate weight.

**WAPE** = `sum|actual - forecast| / sum|actual|` over all points. Primary accuracy metric. It keeps the zero weeks in the numerator where the error is real, and weights by volume, so a 3-unit miss on a 100-unit week does not count the same as a 3-unit miss on a 4-unit week.

**MAPE** = `mean(|actual - forecast| / |actual|)`, undefined at zero and so computed only on the 46.1% of points with non-zero actuals. Reported for continuity, but it describes the easier half of the data and should never be the deciding number.

**Missed-sales share** = actual units in holdout points where `actual > 0` but `forecast < 0.5 units`, as a percentage of the 113,660 total. This is the stockout measure, and it exists because **WAPE cannot see the asymmetry that matters for ordering**: it scores a 5-unit under-forecast identically to a 5-unit over-forecast. In a distribution business those are not the same event — one is carrying cost, the other is a lost sale.

> **Acceptance rule.** A candidate model must not regress on **either** WAPE **or** missed-sales share, against the current best (**60.0% / 0.7%**). A gain on one bought with a loss on the other is not an improvement and will not be accepted as one.

§6 and §7 both show the rule biting on this data.

---

## 6. Result

Single XGBoost regressor per row of the zero-filled dataset. Features: lag 1/2/4 units, trailing 4- and 12-week means, trailing 12-week non-zero share, weeks-since-first-sale, week-of-year, and `location_id` as a categorical. Insufficient-history windows are `NaN` rather than partial means, so the model can branch on "not enough history" instead of reading a short window as a genuinely low mean. Same rolling one-week-ahead setup as the baseline: features for holdout week *t* are built from actuals through *t−1*.

All rows below share identical features, hyperparameters, and seed — **only the loss changes.**

| model | MAPE | **WAPE** | missed pts | missed units | **% units** |
|---|---|---|---|---|---|
| baseline (rolling) | 56.1% | 62.1% | 390 | 3,570 | 3.1% |
| baseline (static) | 55.6% | 64.4% | 328 | 2,897 | 2.5% |
| xgboost (squarederror) | 52.1% | 60.9% | 28 | 334 | 0.3% |
| xgboost (poisson) | 49.7% | 60.5% | 30 | 340 | 0.3% |
| xgboost (tweedie 1.1) | 49.5% | 60.9% | 33 | 353 | 0.3% |
| xgboost (tweedie 1.3) | 49.8% | 60.2% | 47 | 406 | 0.4% |
| xgboost (tweedie 1.5) | 50.1% | 60.0% | 72 | 525 | 0.5% |
| **xgboost (tweedie 1.7)** | **50.5%** | **60.0%** | **110** | **790** | **0.7%** |
| xgboost (tweedie 1.9) | 51.6% | 59.6% | 227 | 1,656 | 1.5% |
| two-stage (soft gate) | 59.2% | 57.4% | 588 | 3,887 | 3.4% |
| two-stage (hard gate .5) | 60.1% | 56.0% | 1,725 | 15,036 | 13.2% |

**Accepted: tweedie 1.7.** 60.0% WAPE at 0.7% missed units — 4.4 points better than the static baseline on WAPE and less than a third of its stockout rate.

**Rejected: tweedie 1.9, despite the better WAPE.** It posts the best single-stage WAPE in the table (59.6%, 0.4 ahead) but more than doubles missed units — 1,656 against 790, 1.5% of demand against 0.7%. Under the two-metric rule that is a regression, so the 0.4-point WAPE edge does not buy acceptance. This is the first time the rule has excluded a plain single-stage model rather than a gated one, and it is the clearest case for keeping the rule: on WAPE alone, 1.9 wins.

Note also that the WAPE-optimal variance power keeps drifting upward as it is allowed to trade away sales — 1.5, 1.7 and 1.9 sit at 60.0, 60.0, 59.6 while missed units run 0.5%, 0.7%, 1.5%. The loss parameter is behaving as a stockout dial, much as the hard-gate threshold does in §7, just less bluntly.

---

## 7. Why the Gated Variants Were Rejected

A two-stage hurdle was tested: `XGBClassifier(binary:logistic)` predicting `units > 0`, combined with the tweedie 1.7 quantity model. Soft gate = `P(sale) × quantity`; hard gate = 0 when `P(sale) < threshold`, else quantity.

**Both beat every single-stage model on WAPE. Both are rejected.**

The hard gate at 0.5 posts the best WAPE in this document — 56.0%, four points better than tweedie 1.7 — while predicting away **13.2% of all holdout units**, against 0.7%. That is 15,036 units of real demand forecast to zero versus 790, a 19× increase. It is not a better forecast; it is the model declining to forecast half the book and being rewarded by a metric that cannot see the consequence.

The threshold sweep makes the trade explicit:

| threshold | MAPE | WAPE | missed pts | missed units | % units |
|---|---|---|---|---|---|
| P ≥ 0.3 | 52.7% | 57.6% | 656 | 5,481 | 4.8% |
| P ≥ 0.4 | 55.8% | 56.6% | 1,156 | 9,827 | 8.6% |
| P ≥ 0.5 | 60.1% | 56.0% | 1,725 | 15,036 | 13.2% |
| P ≥ 0.6 | 65.3% | 55.7% | 2,302 | 20,500 | 18.0% |

- **WAPE gains decelerate while stockouts accelerate.** Across 0.3 → 0.6, WAPE moves 57.6 → 56.6 → 56.0 → 55.7 (1.9 points total, each step smaller) while missed units go 4.8% → 8.6% → 13.2% → 18.0% (each step larger). Every step up the threshold buys less and costs more.
- Even the gentlest setting (0.3) costs 7× the missed units of tweedie 1.7 for 2.4 points of WAPE.

Under a WAPE-only rule the hard gate would be the accepted model. That is what §5 exists to prevent.

---

## 8. The ≤53% Target Is Not Reachable at This Grain

The original ≤53% WAPE target is 7 points below the best acceptable result. The evidence that the gap is structural rather than a tuning problem:

1. **The loss sweep has flattened near 60%.** WAPE across Tweedie variance powers: 60.9 → 60.2 → 60.0 → 60.0 → 59.6. Each step is worth ≤0.4 points, and each is paid for in missed units. Nothing in this direction reaches 53%.
2. **The two-stage model, which directly targets the zero/non-zero structure, could only buy WAPE with stockouts** — and even discarding 13.2% of demand it reaches only 56.0%, still 3 points short of target.
3. **Feature importance shows the model rediscovering the baseline.** `trail_4_mean` leads at 0.343 gain, with the lag features behind it; `week_of_year` at 0.081 never found real seasonality.
4. **More data helped more than any modelling choice did.** The May export gave 62.4% WAPE; the August export gives 60.0% from the identical model and hyperparameters — 2.4 points from 17% more rows and 12 more weeks. No loss function or architecture tried here moved the number that far.

The cause is the grain. **53.9% of holdout points are zero**, so a forecast at `(store, upc, week)` is mostly predicting whether a sale occurs at all, and WAPE's denominator is dominated by weeks whose demand is genuinely unpredictable at this resolution.

> Do not treat MAPE 50.5% as meeting a ≤53% target. MAPE is computed only on the 46.1% of points with non-zero actuals and is not the target metric.

---

## 9. Published Forecasts — Stale Rows Present

`forecast_model.py --write` fits tweedie 1.7 on all 84 weeks and upserts one row per eligible series for the week after the last full week, keyed on `(location_id, store_name, upc, week_start, model_version)`.

The `forecasts` table currently holds **two generations under the same `model_version`**:

| week_start | model_version | rows | predicted units | generated |
|---|---|---|---|---|
| 2026-05-25 | `xgb-tweedie1.7-v1` | 1,610 | 13,016 | 2026-08-19T02:10:50 |
| 2026-08-17 | `xgb-tweedie1.7-v1` | 1,792 | 14,573 | 2026-08-19T02:56:52 |

**The 2026-05-25 rows are stale and should not be read.** They were produced from the May export, before the August reload replaced the underlying data — a different training set, a different eligible population, and a forecast week that has since been overtaken. The upsert key includes `week_start`, so the new run added rows rather than replacing them, and both generations now coexist.

The hazard is that `model_version` alone does not distinguish them. **Any consumer must filter on `week_start`**, or it will pick up 1,610 obsolete rows alongside the 1,792 current ones. The durable fixes are to delete the stale week, or to bump `MODEL_VERSION` whenever the training data is reloaded so that generation is visible in the key. Neither has been done.

---

## 10. Where to Go Next

Tuning this setup further is not worth the effort — §6–§8 show the grain, not the model, is the binding constraint. The directions that change the constraint:

- **Coarser grain.** Store × category, or biweekly/monthly buckets. Trades resolution for series dense enough to forecast, and directly attacks the 53.9% zero rate.
- **Croston-type methods.** Model demand size and inter-arrival interval separately rather than averaging through the zeros.
- **Reframe the target.** If the ordering decision only needs "will this sell, and roughly how much", a classification + quantile approach scored on stockout cost and carrying cost may serve better than a point forecast scored on WAPE. This would also replace the two-metric rule with a single cost-based one.
- **Keep accumulating history.** The one lever that measurably moved WAPE this cycle was more data, not a better model.
- **Renegotiate the ≤53% figure** against whichever of the above is chosen. It was set before the zero rate at this grain was known.

---

## 11. Changes From the May 2026 Figures

| | May export | August export |
|---|---|---|
| Sale rows | 106,867 | 124,472 |
| Zero-filled grid | 232,600 rows / 72 weeks | 288,489 rows / 84 weeks |
| Series evaluated | 1,490 | 1,685 |
| Holdout | 2026-03-30 .. 2026-05-18 | 2026-06-22 .. 2026-08-10 |
| Zero share of holdout | 51.6% | 53.9% |
| Baseline (static) | 66.4% / 3.1% | 64.4% / 2.5% |
| **Accepted model** | 62.4% / 1.6% | **60.0% / 0.7%** |

The accepted model is the same in both — tweedie 1.7, same features, same hyperparameters, same seed. Every improvement above came from more data.

---

## 12. Environment Caveat: libomp

`requirements.txt` pins `xgboost==2.1.4` and `scikit-learn==1.6.1`, but **`pip install -r requirements.txt` alone will not produce a working xgboost on macOS.** The wheel needs the OpenMP runtime (`libomp.dylib`), which is not a pip package, and Homebrew is not installed on the current machine.

It currently resolves through a venv-local workaround: the `libomp.dylib` vendored inside scikit-learn's wheel was copied to `venv/lib/`, and an rpath to it was added to `libxgboost.dylib` with `install_name_tool`. Contained in the gitignored venv, reversible by reinstalling xgboost, no sudo required — and **not reproducible on another machine.**

This needs a real fix before anyone else runs `forecast_model.py`. Options: install Homebrew and `brew install libomp`; add a setup script that performs the rpath patch; or switch to scikit-learn's `HistGradientBoostingRegressor`, which ships its own OpenMP and would remove the dependency entirely.
