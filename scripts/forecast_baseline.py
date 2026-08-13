#!/usr/bin/env python3
"""
scripts/forecast_baseline.py
----------------------------
Backtest a trailing-mean baseline on the weekly demand dataset built by
forecast_prep.py. Reads .env for credentials.

Read-only: writes nothing back to the DB.

Setup
  Dataset   weekly units per (location_id, store_name, upc), zero-filled from
            each series' first sale week, partial boundary weeks dropped.
  Holdout   the last HOLDOUT_WEEKS full weeks of the grid.
  Baseline  trailing LOOKBACK-week mean.
  Eligible  series with at least MIN_ACTIVE_WEEKS non-zero weeks strictly
            before the holdout.

Two variants of the same baseline are scored, because "trailing 4-week mean"
is ambiguous once the horizon is longer than one week:

  rolling   one-step-ahead — each holdout week is predicted from the 4 weeks
            immediately before it, including earlier holdout actuals. Measures
            "how good is this rule if you re-forecast every week".
  static    computed once from the last 4 training weeks and held flat across
            all 8 holdout weeks. Measures "how good is this rule if you forecast
            the whole horizon up front", which is the harder, more realistic
            question for an ordering cycle.

Metrics are pooled over every (series, holdout week) point, not averaged per
series, so heavy sellers carry proportionate weight.
  MAPE  mean of |actual - forecast| / |actual| over points with non-zero actual.
  WAPE  sum |actual - forecast| / sum |actual| over all points.
"""

from datetime import timedelta

from supabase import create_client

from forecast_prep import SUPABASE_KEY, SUPABASE_URL, build_dataset

HOLDOUT_WEEKS = 8
LOOKBACK = 4
MIN_ACTIVE_WEEKS = 12


def trailing_mean(values):
    return sum(values) / len(values) if values else 0.0


def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("── Forecast Baseline: trailing 4-week mean ──────────────────────────\n")

    filled, grid, _dropped, _raw, _min_d, _max_d = build_dataset(sb)

    holdout = grid[-HOLDOUT_WEEKS:]
    train = grid[:-HOLDOUT_WEEKS]
    print(f"  Train weeks:    {train[0]} .. {train[-1]}  ({len(train)} weeks)")
    print(f"  Holdout weeks:  {holdout[0]} .. {holdout[-1]}  ({len(holdout)} weeks)")

    # ── Select eligible series ────────────────────────────────────────────

    eligible = []
    for series, weeks in filled.items():
        active = sum(1 for wk in train if weeks.get(wk, 0) != 0)
        if active >= MIN_ACTIVE_WEEKS:
            eligible.append(series)

    print(f"\n  Series in dataset:      {len(filled):,}")
    print(f"  Series evaluated:       {len(eligible):,}"
          f"  (≥{MIN_ACTIVE_WEEKS} active weeks before holdout)")
    print(f"  Series excluded:        {len(filled) - len(eligible):,}")

    if not eligible:
        print("\n⛔  No series met the eligibility threshold.")
        return

    # ── Score ─────────────────────────────────────────────────────────────

    abs_err = {"rolling": 0.0, "static": 0.0}
    pct_err = {"rolling": 0.0, "static": 0.0}
    actual_sum = 0.0
    points = 0
    nonzero_points = 0

    for series in eligible:
        weeks = filled[series]

        # Static forecast: mean of the last LOOKBACK training weeks.
        static_fc = trailing_mean([weeks.get(wk, 0) for wk in train[-LOOKBACK:]])

        for wk in holdout:
            actual = weeks.get(wk, 0)

            # Rolling forecast: the LOOKBACK weeks immediately before wk.
            prior = [wk - timedelta(days=7 * i) for i in range(1, LOOKBACK + 1)]
            rolling_fc = trailing_mean([weeks.get(p, 0) for p in prior])

            points += 1
            actual_sum += abs(actual)

            for name, fc in (("rolling", rolling_fc), ("static", static_fc)):
                err = abs(actual - fc)
                abs_err[name] += err
                if actual != 0:
                    pct_err[name] += err / abs(actual)

            if actual != 0:
                nonzero_points += 1

    print(f"\n  Holdout points:         {points:,}"
          f"  ({len(eligible):,} series × {len(holdout)} weeks)")
    print(f"  Non-zero actuals:       {nonzero_points:,}"
          f"  ({100 * nonzero_points / points:.1f}% — MAPE denominator)")

    # ── Report ────────────────────────────────────────────────────────────

    print("\n── Accuracy ─────────────────────────────────────────────────────────\n")
    print(f"  {'variant':<10}{'MAPE':>12}{'WAPE':>12}")
    for name in ("rolling", "static"):
        mape = 100 * pct_err[name] / nonzero_points if nonzero_points else float("nan")
        wape = 100 * abs_err[name] / actual_sum if actual_sum else float("nan")
        print(f"  {name:<10}{mape:>11.1f}%{wape:>11.1f}%")

    print("\n✅  Backtest complete. Nothing written to the DB.")


if __name__ == "__main__":
    main()
