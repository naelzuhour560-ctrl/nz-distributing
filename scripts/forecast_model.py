#!/usr/bin/env python3
"""
scripts/forecast_model.py
-------------------------
XGBoost regressor on the weekly demand dataset, scored against the trailing-mean
baseline in docs/phase-3-baseline.md. Reads .env for credentials.

Read-only: writes nothing back to the DB.

Comparability — the whole point of this script is a number that can be put next
to the baseline, so eligibility, holdout, and metrics are imported from
forecast_baseline.py rather than reimplemented:

  same 1,490 eligible series   (>=12 active weeks before the holdout)
  same 8-week holdout          (2026-03-30 .. 2026-05-18)
  same rolling one-week-ahead  features for holdout week t are built from
                               actuals through t-1, exactly as the rolling
                               baseline averages actuals through t-1
  same pooled metrics          MAPE on non-zero actuals, WAPE on all points

Training rows come from every series in the dataset, not just the eligible
1,490 — a sparse series still carries signal about how demand behaves. Only
the *evaluation* is restricted to the eligible set.
"""

from datetime import timedelta

import numpy as np
import pandas as pd
from supabase import create_client
from xgboost import XGBClassifier, XGBRegressor

from forecast_baseline import (
    HOLDOUT_WEEKS,
    baseline_points,
    pooled_metrics,
    select_eligible,
)
from forecast_prep import SUPABASE_KEY, SUPABASE_URL, build_dataset

TRAIL_SHORT = 4
TRAIL_LONG = 12
SEED = 17

# A forecast below this rounds down to "order nothing" — used to count the
# real sales a model predicts away.
ORDER_FLOOR = 0.5

# Hard-gate thresholds on P(sale) to sweep.
GATE_THRESHOLDS = [0.3, 0.4, 0.5, 0.6]

# Identical features, hyperparameters, and seed across all of these — the only
# thing that varies is the loss. Count objectives are worth a look here because
# the target is non-negative integer units that are zero ~half the time, which
# is not what squared error assumes.
OBJECTIVES = [
    ("squarederror", "reg:squarederror", {}),
    ("poisson", "count:poisson", {}),
    ("tweedie 1.1", "reg:tweedie", {"tweedie_variance_power": 1.1}),
    ("tweedie 1.3", "reg:tweedie", {"tweedie_variance_power": 1.3}),
    ("tweedie 1.5", "reg:tweedie", {"tweedie_variance_power": 1.5}),
    ("tweedie 1.7", "reg:tweedie", {"tweedie_variance_power": 1.7}),
    ("tweedie 1.9", "reg:tweedie", {"tweedie_variance_power": 1.9}),
]

BASE_PARAMS = dict(
    n_estimators=400,
    learning_rate=0.05,
    max_depth=6,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=5,
    tree_method="hist",
    enable_categorical=True,
    random_state=SEED,
    n_jobs=-1,
)

FEATURES = [
    "lag_1",
    "lag_2",
    "lag_4",
    "trail_4_mean",
    "trail_12_mean",
    "trail_12_nonzero_share",
    "weeks_since_first_sale",
    "week_of_year",
    "location_id",
]


def window(weeks, wk, n):
    """
    The n weeks immediately before wk, or None if any of them predates the
    series' first sale.

    Returning None rather than a partial window keeps "insufficient history"
    distinct from "genuinely quiet stretch" — XGBoost routes the resulting NaN
    down its own branch instead of reading a short window as a real low mean.
    """
    prior = [wk - timedelta(days=7 * i) for i in range(1, n + 1)]
    if any(p not in weeks for p in prior):
        return None
    return [weeks[p] for p in prior]


def build_rows(filled, target_weeks, series_filter=None):
    """
    One row per (series, week) over target_weeks, with lag/trailing features
    built from actuals strictly before the target week.
    """
    rows = []
    for series, weeks in filled.items():
        if series_filter is not None and series not in series_filter:
            continue

        location_id, store_name, upc = series
        first_week = min(weeks)

        for wk in target_weeks:
            if wk not in weeks:
                continue

            short = window(weeks, wk, TRAIL_SHORT)
            long_ = window(weeks, wk, TRAIL_LONG)
            lags = {n: weeks.get(wk - timedelta(days=7 * n)) for n in (1, 2, 4)}

            rows.append({
                "location_id": location_id,
                "store_name": store_name,
                "upc": upc,
                "week": wk,
                "lag_1": lags[1],
                "lag_2": lags[2],
                "lag_4": lags[4],
                "trail_4_mean": sum(short) / TRAIL_SHORT if short else None,
                "trail_12_mean": sum(long_) / TRAIL_LONG if long_ else None,
                "trail_12_nonzero_share": (
                    sum(1 for v in long_ if v != 0) / TRAIL_LONG if long_ else None
                ),
                "weeks_since_first_sale": (wk - first_week).days // 7,
                "week_of_year": wk.isocalendar()[1],
                "units": weeks[wk],
            })

    return pd.DataFrame(rows)


def missed_sales(points, floor=ORDER_FLOOR):
    """
    Holdout points with real demand that the model effectively predicts away:
    actual > 0 but forecast < floor units, i.e. rounds down to "order nothing".

    Returns (count, actual units in those points). WAPE and MAPE both treat an
    under-forecast the same as an over-forecast of equal size; in an ordering
    context these are stockouts, so they are counted separately.
    """
    missed = [(a, f) for a, f in points if a > 0 and f < floor]
    return len(missed), sum(a for a, _ in missed)


def as_model_frame(df, loc_dtype):
    """Feature matrix with location_id as a categorical of fixed levels."""
    X = df[FEATURES].copy()
    X["location_id"] = X["location_id"].astype(loc_dtype)
    return X


def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("── Forecast Model: XGBoost vs trailing-mean baseline ────────────────\n")

    filled, grid, _dropped, _raw, _min_d, _max_d = build_dataset(sb)

    holdout = grid[-HOLDOUT_WEEKS:]
    train_weeks = grid[:-HOLDOUT_WEEKS]
    eligible = select_eligible(filled, train_weeks)
    eligible_set = set(eligible)

    print(f"  Train weeks:    {train_weeks[0]} .. {train_weeks[-1]}"
          f"  ({len(train_weeks)} weeks)")
    print(f"  Holdout weeks:  {holdout[0]} .. {holdout[-1]}  ({len(holdout)} weeks)")
    print(f"  Series evaluated: {len(eligible):,} of {len(filled):,}")

    # ── Build training table ──────────────────────────────────────────────

    print("\n  Building features...", flush=True)
    train_df = build_rows(filled, train_weeks)
    eval_df = build_rows(filled, holdout, series_filter=eligible_set)

    loc_dtype = pd.CategoricalDtype(
        sorted({s[0] for s in filled}), ordered=False
    )
    X_train = as_model_frame(train_df, loc_dtype)
    y_train = train_df["units"]
    X_eval = as_model_frame(eval_df, loc_dtype)

    print(f"  Training rows:  {len(train_df):,}  (all series, weeks before holdout)")
    print(f"  Eval rows:      {len(eval_df):,}  "
          f"({len(eligible):,} series × {len(holdout)} weeks)")

    # ── Train one model per objective ─────────────────────────────────────

    actuals = eval_df["units"].tolist()
    base = baseline_points(filled, eligible, train_weeks, holdout)

    points = {
        "baseline (rolling)": base["rolling"],
        "baseline (static)": base["static"],
    }
    models = {}

    for label, objective, extra in OBJECTIVES:
        print(f"\n  Training XGBoost [{label}]...", flush=True)
        model = XGBRegressor(objective=objective, **BASE_PARAMS, **extra)
        model.fit(X_train, y_train)

        # Units cannot be negative; a negative prediction is never the better
        # guess. (Poisson and Tweedie predict through a log link and are
        # already non-negative — this only bites squared error.)
        preds = model.predict(X_eval).clip(min=0)

        models[label] = model
        points[f"xgboost ({label})"] = list(zip(actuals, preds.tolist()))

    # ── Two-stage (hurdle-style) ──────────────────────────────────────────
    #
    # Stage 1 predicts whether the week sells at all; stage 2 is the tweedie
    # 1.7 regressor above, reused unchanged since it is trained on exactly the
    # same rows.
    #
    # Caveat worth keeping in view when reading the soft-gate number: a Tweedie
    # expectation already integrates over the zero mass, so multiplying it by
    # P(sale) discounts for zeros a second time. The hard gate does not have
    # that problem — it either zeros the prediction or passes it through.

    print("\n  Training XGBoost [two-stage classifier]...", flush=True)
    clf = XGBClassifier(objective="binary:logistic", **BASE_PARAMS)
    clf.fit(X_train, (y_train > 0).astype(int))

    p_sale = clf.predict_proba(X_eval)[:, 1]
    quantity = models["tweedie 1.7"].predict(X_eval).clip(min=0)

    points["two-stage (soft gate)"] = list(zip(actuals, (p_sale * quantity).tolist()))

    gate_points = {}
    for thr in GATE_THRESHOLDS:
        gated = np.where(p_sale < thr, 0.0, quantity)
        gate_points[thr] = list(zip(actuals, gated.tolist()))
    points["two-stage (hard gate .5)"] = gate_points[0.5]

    # ── Score ─────────────────────────────────────────────────────────────

    results = {name: pooled_metrics(pts) for name, pts in points.items()}

    shape = results["baseline (rolling)"]
    total_units = sum(a for a, _ in points["baseline (rolling)"])
    print(f"\n  Holdout points: {shape['points']:,}")
    print(f"  Non-zero actuals: {shape['nonzero']:,}"
          f"  ({100 * shape['nonzero'] / shape['points']:.1f}% — MAPE denominator)")
    print(f"  Total actual units: {total_units:,}")

    print("\n── Accuracy ─────────────────────────────────────────────────────────\n")
    print(f"  {'model':<24}{'MAPE':>9}{'WAPE':>9}"
          f"{'missed':>10}{'units':>12}{'% units':>10}")
    for name, m in results.items():
        cnt, units = missed_sales(points[name])
        print(f"  {name:<24}{m['mape']:>8.1f}%{m['wape']:>8.1f}%"
              f"{cnt:>10,}{units:>12,}{100 * units / total_units:>9.1f}%")
    print(f"\n  missed = holdout points with actual > 0 but forecast < "
          f"{ORDER_FLOOR} units (a stockout)")

    base_wape = results["baseline (static)"]["wape"]
    best = min(
        (n for n in results if n.startswith("xgboost")),
        key=lambda n: results[n]["wape"],
    )
    delta = base_wape - results[best]["wape"]
    print(f"\n  Best single-stage by WAPE: {best} — {delta:+.1f} pts vs static"
          f" baseline  ({'better' if delta > 0 else 'worse'})")

    overall = min(
        (n for n in results if not n.startswith("baseline")),
        key=lambda n: results[n]["wape"],
    )
    o_delta = base_wape - results[overall]["wape"]
    print(f"  Best overall by WAPE:      {overall} — {o_delta:+.1f} pts vs static"
          f" baseline  ({'better' if o_delta > 0 else 'worse'})")

    # ── Hard-gate threshold sweep ─────────────────────────────────────────
    #
    # The threshold is the WAPE/stockout dial: a lower gate lets more marginal
    # weeks through, giving up WAPE to avoid predicting real sales away.

    print("\n── Hard-gate threshold sweep ────────────────────────────────────────\n")
    print(f"  {'threshold':<12}{'MAPE':>9}{'WAPE':>9}"
          f"{'missed':>10}{'units':>12}{'% units':>10}")
    for thr in GATE_THRESHOLDS:
        m = pooled_metrics(gate_points[thr])
        cnt, units = missed_sales(gate_points[thr])
        print(f"  P >= {thr:<7.1f}{m['mape']:>8.1f}%{m['wape']:>8.1f}%"
              f"{cnt:>10,}{units:>12,}{100 * units / total_units:>9.1f}%")

    # ── Feature importance ────────────────────────────────────────────────

    print(f"\n── Feature importance (gain, {best.split('(')[1][:-1]}) ──────────────────\n")
    gains = sorted(
        zip(FEATURES, models[best.split("(")[1][:-1]].feature_importances_),
        key=lambda x: -x[1],
    )
    for name, gain in gains:
        print(f"  {name:<26}{gain:>8.3f}")

    print("\n✅  Backtest complete. Nothing written to the DB.")


if __name__ == "__main__":
    main()
