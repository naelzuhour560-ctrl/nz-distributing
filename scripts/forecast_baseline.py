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


def select_eligible(filled, train):
    """Series with at least MIN_ACTIVE_WEEKS non-zero weeks before the holdout."""
    return [
        series
        for series, weeks in filled.items()
        if sum(1 for wk in train if weeks.get(wk, 0) != 0) >= MIN_ACTIVE_WEEKS
    ]


def baseline_points(filled, eligible, train, holdout):
    """
    Score both baseline variants over the holdout.

    Returns {variant: [(actual, forecast), ...]} pooled across all series and
    holdout weeks.
    """
    points = {"rolling": [], "static": []}

    for series in eligible:
        weeks = filled[series]
        static_fc = trailing_mean([weeks.get(wk, 0) for wk in train[-LOOKBACK:]])

        for wk in holdout:
            actual = weeks.get(wk, 0)
            prior = [wk - timedelta(days=7 * i) for i in range(1, LOOKBACK + 1)]
            rolling_fc = trailing_mean([weeks.get(p, 0) for p in prior])

            points["rolling"].append((actual, rolling_fc))
            points["static"].append((actual, static_fc))

    return points


def pooled_metrics(points):
    """
    MAPE and WAPE pooled over (actual, forecast) pairs.

    MAPE is defined only where actual != 0; WAPE uses every point. See
    docs/phase-3-baseline.md for why WAPE is the primary metric.
    """
    abs_err = sum(abs(a - f) for a, f in points)
    actual_sum = sum(abs(a) for a, _ in points)
    nonzero = [(a, f) for a, f in points if a != 0]
    pct_err = sum(abs(a - f) / abs(a) for a, f in nonzero)

    return {
        "mape": 100 * pct_err / len(nonzero) if nonzero else float("nan"),
        "wape": 100 * abs_err / actual_sum if actual_sum else float("nan"),
        "points": len(points),
        "nonzero": len(nonzero),
    }


def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("── Forecast Baseline: trailing 4-week mean ──────────────────────────\n")

    filled, grid, _dropped, _raw, _min_d, _max_d = build_dataset(sb)

    holdout = grid[-HOLDOUT_WEEKS:]
    train = grid[:-HOLDOUT_WEEKS]
    print(f"  Train weeks:    {train[0]} .. {train[-1]}  ({len(train)} weeks)")
    print(f"  Holdout weeks:  {holdout[0]} .. {holdout[-1]}  ({len(holdout)} weeks)")

    # ── Select eligible series ────────────────────────────────────────────

    eligible = select_eligible(filled, train)

    print(f"\n  Series in dataset:      {len(filled):,}")
    print(f"  Series evaluated:       {len(eligible):,}"
          f"  (≥{MIN_ACTIVE_WEEKS} active weeks before holdout)")
    print(f"  Series excluded:        {len(filled) - len(eligible):,}")

    if not eligible:
        print("\n⛔  No series met the eligibility threshold.")
        return

    # ── Score ─────────────────────────────────────────────────────────────

    points = baseline_points(filled, eligible, train, holdout)
    metrics = {name: pooled_metrics(pts) for name, pts in points.items()}

    shape = metrics["rolling"]
    print(f"\n  Holdout points:         {shape['points']:,}"
          f"  ({len(eligible):,} series × {len(holdout)} weeks)")
    print(f"  Non-zero actuals:       {shape['nonzero']:,}"
          f"  ({100 * shape['nonzero'] / shape['points']:.1f}% — MAPE denominator)")

    # ── Report ────────────────────────────────────────────────────────────

    print("\n── Accuracy ─────────────────────────────────────────────────────────\n")
    print(f"  {'variant':<10}{'MAPE':>12}{'WAPE':>12}")
    for name in ("rolling", "static"):
        m = metrics[name]
        print(f"  {name:<10}{m['mape']:>11.1f}%{m['wape']:>11.1f}%")

    print("\n✅  Backtest complete. Nothing written to the DB.")


if __name__ == "__main__":
    main()
