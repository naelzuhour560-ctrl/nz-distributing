# Phase 3: Forecast Baseline and Week 9 Result

The trailing-mean baseline, the Week 9 model measured against it, and the acceptance rule for anything that follows. Built by `scripts/forecast_prep.py` (dataset), `scripts/forecast_baseline.py` (baseline), and `scripts/forecast_model.py` (model). All three are read-only — nothing is written to the DB.

**Result in one line:** tweedie 1.7 single-stage XGBoost at **62.4% WAPE / 1.6% missed units**, against a baseline of **66.4% / 3.1%**. Better on both metrics, and 9 points short of the original ≤53% target — which section 8 argues is not reachable at this grain.

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

17 series sold only in the dropped boundary weeks and fall out entirely. Post-fill density is **29.4% non-zero** — this is intermittent demand, and that fact drives everything below.

---

## 2. Eligibility

A series is scored only if it has **≥12 non-zero weeks strictly before the holdout**. This screens out series too sparse or too new to evaluate meaningfully.

| | series |
|---|---|
| In dataset | 4,420 |
| **Evaluated** | **1,490** |
| Excluded | 2,930 |

Two-thirds of series are excluded. Every number in this document therefore describes the densest third of the catalogue, not the whole book. **Any model compared against these figures must be scored on the same 1,490 series.**

The Week 9 model *trains* on all 4,420 series — a sparse series still carries signal about how demand behaves — but is *evaluated* only on the eligible 1,490.

---

## 3. Holdout

| | |
|---|---|
| Train | 2025-01-06 .. 2026-03-23 (64 weeks) |
| Holdout | 2026-03-30 .. 2026-05-18 (8 weeks) |
| Points | 11,920 (1,490 series × 8 weeks) |
| Non-zero actuals | 5,772 (48.4%) |
| Total actual units | 115,437 |

**51.6% of holdout points are zero.** That single fact explains most of what follows.

---

## 4. Baseline

"Trailing 4-week mean" is ambiguous once the horizon exceeds one week, so both readings are scored:

- **rolling** — one-step-ahead. Each holdout week is predicted from the 4 weeks immediately before it, including earlier holdout actuals. Answers *"how good is this rule if you re-forecast every week?"*
- **static** — computed once from the last 4 training weeks, held flat across all 8 holdout weeks. Answers *"how good is this rule if you forecast the whole horizon up front?"* — the realistic question for an ordering cycle, and the reference figure.

| variant | MAPE | **WAPE** | missed units |
|---|---|---|---|
| rolling | 55.6% | **66.1%** | 3.0% |
| static | 54.5% | **66.4%** | 3.1% |

**The two land within a point of each other.** Refreshing weekly with the latest actuals buys essentially nothing — the week-to-week variation at this grain is close to noise, with no short-term signal for a mean to track.

---

## 5. Metrics: the Two-Metric Rule

Metrics are pooled over all (series, week) points rather than averaged per series, so heavy sellers carry proportionate weight.

**WAPE** = `sum|actual - forecast| / sum|actual|` over all points. Primary accuracy metric. It keeps the zero weeks in the numerator where the error is real, and weights by volume, so a 3-unit miss on a 100-unit week does not count the same as a 3-unit miss on a 4-unit week.

**MAPE** = `mean(|actual - forecast| / |actual|)`, undefined at zero and so computed only on the 48.4% of points with non-zero actuals. Reported for continuity, but it describes the easier half of the data and should never be the deciding number.

**Missed-sales share** = actual units in holdout points where `actual > 0` but `forecast < 0.5 units`, as a percentage of the 115,437 total. This is the stockout measure, and it exists because **WAPE cannot see the asymmetry that matters for ordering**: it scores a 5-unit under-forecast identically to a 5-unit over-forecast. In a distribution business those are not the same event — one is carrying cost, the other is a lost sale. Section 7 shows a model exploiting exactly that blind spot.

> **Acceptance rule.** A candidate model must not regress on **either** WAPE **or** missed-sales share, against the current best (62.4% / 1.6%). A gain on one bought with a loss on the other is not an improvement and will not be accepted as one.

---

## 6. Week 9 Result

Single XGBoost regressor per row of the zero-filled dataset. Features: lag 1/2/4 units, trailing 4- and 12-week means, trailing 12-week non-zero share, weeks-since-first-sale, week-of-year, and `location_id` as a categorical. Insufficient-history windows are `NaN` rather than partial means, so the model can branch on "not enough history" instead of reading a short window as a genuinely low mean. Same rolling one-week-ahead setup as the baseline: features for holdout week *t* are built from actuals through *t−1*.

All rows below share identical features, hyperparameters, and seed — **only the loss changes.**

| model | MAPE | **WAPE** | missed pts | missed units | **% units** |
|---|---|---|---|---|---|
| baseline (rolling) | 55.6% | 66.1% | 321 | 3,491 | 3.0% |
| baseline (static) | 54.5% | 66.4% | 286 | 3,626 | 3.1% |
| xgboost (squarederror) | 51.2% | 65.3% | 1 | 5 | 0.0% |
| xgboost (poisson) | 51.0% | 63.8% | 1 | 5 | 0.0% |
| xgboost (tweedie 1.1) | 51.0% | 63.6% | 14 | 187 | 0.2% |
| xgboost (tweedie 1.3) | 51.4% | 63.0% | 80 | 1,080 | 0.9% |
| xgboost (tweedie 1.5) | 52.2% | 62.8% | 96 | 1,307 | 1.1% |
| **xgboost (tweedie 1.7)** | **52.0%** | **62.4%** | **179** | **1,888** | **1.6%** |
| xgboost (tweedie 1.9) | 53.5% | 62.4% | 278 | 2,831 | 2.5% |
| two-stage (soft gate) | 60.6% | 60.2% | 601 | 5,447 | 4.7% |
| two-stage (hard gate .5) | 60.2% | 59.4% | 1,501 | 15,692 | 13.6% |

**Accepted: tweedie 1.7.** 62.4% WAPE at 1.6% missed units — 4.0 points better than the static baseline on WAPE and half its stockout rate. It is the only class of result here that improves both metrics at once.

Two things the sweep establishes:

- **Matching the loss to the target mattered more than the features.** Count objectives beat squared error by 2.9 points of WAPE with everything else held identical. The target is non-negative integer counts that are zero half the time; squared error assumes symmetric continuous noise.
- **Tweedie 1.9 is not preferred despite tying on WAPE.** It has worse MAPE (53.5% vs 52.0%) and 50% more missed units. Its feature importances also destabilise — `week_of_year` jumps to 0.147 while `lag_1` collapses to 0.094 — which reads as over-shrinkage rather than signal.

---

## 7. Why the Gated Variants Were Rejected

A two-stage hurdle was tested: `XGBClassifier(binary:logistic)` predicting `units > 0`, combined with the tweedie 1.7 quantity model. Soft gate = `P(sale) × quantity`; hard gate = 0 when `P(sale) < threshold`, else quantity.

**Both beat every single-stage model on WAPE. Both were rejected.**

The hard gate at 0.5 posts the best WAPE in this document — 59.4%, three points better than tweedie 1.7 — while predicting away **13.6% of all holdout units**, against 1.6%. That is 15,692 units of real demand forecast to zero versus 1,888, an 8× increase. It is not a better forecast; it is the model declining to forecast half the book and being rewarded by a metric that cannot see the consequence.

The threshold sweep makes the trade explicit:

| threshold | MAPE | WAPE | missed pts | missed units | % units |
|---|---|---|---|---|---|
| P ≥ 0.3 | 53.5% | 61.0% | 617 | 6,636 | 5.7% |
| P ≥ 0.4 | 56.0% | 60.0% | 998 | 10,516 | 9.1% |
| P ≥ 0.5 | 60.2% | 59.4% | 1,501 | 15,692 | 13.6% |
| P ≥ 0.6 | 67.2% | **59.4%** | 2,203 | 23,226 | 20.1% |

- **WAPE gains flatten exactly where stockouts accelerate.** Across 0.3 → 0.6, WAPE moves 61.0 → 60.0 → 59.4 → 59.4 (1.6 points total, decelerating to nothing) while missed units go 5.7% → 9.1% → 13.6% → 20.1% (accelerating). Every step up the threshold buys less and costs more.
- **Threshold 0.6 is strictly dominated** — identical WAPE to 0.5, 48% more missed units, 7 points worse MAPE. No objective prefers it.
- Even the gentlest setting (0.3) costs 3.5× the missed units of tweedie 1.7 for 1.4 points of WAPE.

This is the case that motivated the two-metric rule in section 5. Under a WAPE-only rule the hard gate would have been accepted.

Worth recording as a mild surprise: multiplying a Tweedie expectation by `P(sale)` double-discounts the zero mass, since the Tweedie expectation already integrates over it. That was expected to hurt. It *helped* WAPE — shrinking toward zero reduces absolute error on the 51.6% of points that are zero — which is itself evidence of how strongly WAPE rewards under-forecasting here.

---

## 8. The ≤53% Target Is Not Reachable at This Grain

The original ≤53% WAPE target is 9.4 points below the best honest result. Three independent lines of evidence say the gap is structural, not a tuning problem:

1. **The loss sweep converged.** WAPE across Tweedie variance powers: 63.6 → 63.0 → 62.8 → 62.4 → 62.4. The curve flattens at 1.7 and does not improve at 1.9. There is no remaining gain from matching the loss more carefully.
2. **The two-stage model, which directly targets the zero/non-zero structure, could only buy WAPE with stockouts.** The one architecture aimed squarely at intermittency reached 59.4% — still 6 points short of target — and only by discarding 13.6% of demand. Even that unacceptable trade does not reach ≤53%.
3. **Feature importance shows the model rediscovering the baseline.** `trail_4_mean` and the lag features dominate gain; `week_of_year` never found real seasonality. Nine engineered features and 400 trees improved on a 4-week mean by 4 points, which is the size of gain available when the underlying signal is thin.

The cause is the grain. **51.6% of holdout points are zero**, so a forecast at `(store, upc, week)` is mostly predicting whether a sale occurs at all, and WAPE's denominator is dominated by weeks whose demand is genuinely unpredictable at this resolution. No model choice fixes that; only a change of grain or metric does.

> Do not treat MAPE 52.0% as meeting a ≤53% target. MAPE is computed only on the 48.4% of points with non-zero actuals and is not the target metric.

---

## 9. Environment Caveat: libomp

`requirements.txt` pins `xgboost==2.1.4` and `scikit-learn==1.6.1`, but **`pip install -r requirements.txt` alone will not produce a working xgboost on macOS.** The wheel needs the OpenMP runtime (`libomp.dylib`), which is not a pip package, and Homebrew is not installed on the current machine.

It currently resolves through a venv-local workaround: the `libomp.dylib` vendored inside scikit-learn's wheel was copied to `venv/lib/`, and an rpath to it was added to `libxgboost.dylib` with `install_name_tool`. Contained in the gitignored venv, reversible by reinstalling xgboost, no sudo required — and **not reproducible on another machine.**

This needs a real fix before anyone else runs `forecast_model.py`. Options: install Homebrew and `brew install libomp`; add a setup script that performs the rpath patch; or switch to scikit-learn's `HistGradientBoostingRegressor`, which ships its own OpenMP and would remove the dependency entirely.

---

## 10. Where to Go Next

Tuning this setup further is not worth the effort — sections 6–8 show the grain, not the model, is the binding constraint. The directions that change the constraint:

- **Coarser grain.** Store × category, or biweekly/monthly buckets. Trades resolution for series dense enough to forecast, and directly attacks the 51.6% zero rate.
- **Croston-type methods.** Model demand size and inter-arrival interval separately rather than averaging through the zeros.
- **Reframe the target.** If the ordering decision only needs "will this sell, and roughly how much", a classification + quantile approach scored on stockout cost and carrying cost may serve better than a point forecast scored on WAPE. This would also replace the two-metric rule with a single cost-based one.
- **Renegotiate the ≤53% figure** against whichever of the above is chosen. It was set before the zero rate at this grain was known.
