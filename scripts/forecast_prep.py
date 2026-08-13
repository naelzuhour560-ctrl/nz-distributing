#!/usr/bin/env python3
"""
scripts/forecast_prep.py
------------------------
Build the weekly demand dataset that forecasting will run on, and report its
shape. Reads .env for credentials.

Read-only: this script writes nothing back to the DB. It exists to validate
that the aggregation produces a sane dataset before anything is persisted.

Grain: one row per (location_id, store_name, upc, week_start), where week_start
is the Monday of the week containing calendar_date. Only Sale rows are counted
— Return and Buyback rows are separate transaction types and would net against
demand rather than describe it.
"""

import os
import sys
from collections import defaultdict
from datetime import date, timedelta

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

PAGE_SIZE = 1000


def week_start(iso_date):
    """Monday of the week containing an ISO date string."""
    d = date.fromisoformat(iso_date)
    return d - timedelta(days=d.weekday())


def fetch_sale_rows(sb, verbose=True):
    """
    Yield every Sale row from invoice_lines, PAGE_SIZE per request.

    Ordered by id so the pages form a stable window over the table — an
    unordered .range() can repeat or skip rows between requests.
    """
    offset = 0
    while True:
        r = (
            sb.table("invoice_lines")
            .select("location_id,store_name,upc,units,calendar_date")
            .eq("transaction_type", "Sale")
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        yield from r.data
        if len(r.data) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        if verbose and offset % 20000 == 0:
            print(f"  fetched {offset:,} rows...", flush=True)


def aggregate_weekly(sb, verbose=True):
    """
    Fetch every Sale row and sum units into (location_id, store_name, upc,
    week_start) buckets.

    Returns (weekly, min_date, max_date) where weekly is a plain dict and the
    dates are the ISO bounds of the underlying calendar_date values.
    """
    expected = (
        sb.table("invoice_lines")
        .select("id", count="exact")
        .eq("transaction_type", "Sale")
        .execute()
        .count
    )
    if verbose:
        print(f"Sale rows in invoice_lines: {expected:,}\n")

    weekly = defaultdict(int)
    fetched = 0
    min_date = None
    max_date = None

    for row in fetch_sale_rows(sb, verbose=verbose):
        fetched += 1
        d = row["calendar_date"]
        if min_date is None or d < min_date:
            min_date = d
        if max_date is None or d > max_date:
            max_date = d
        key = (
            row["location_id"],
            row["store_name"],
            row["upc"],
            week_start(d),
        )
        weekly[key] += row["units"]

    if verbose:
        print(f"  fetched {fetched:,} rows (complete)\n")

    if fetched != expected:
        print(f"⚠️  Fetched {fetched:,} rows but the table reports {expected:,} "
              f"Sale rows — pagination may have skipped or repeated rows.\n")

    if not weekly:
        print("⛔  No Sale rows found — nothing to aggregate.")
        sys.exit(1)

    return dict(weekly), min_date, max_date


def week_grid(first, last):
    """Contiguous Monday starts from first to last, inclusive."""
    weeks = []
    w = first
    while w <= last:
        weeks.append(w)
        w += timedelta(days=7)
    return weeks


def trim_partial_weeks(weekly, min_date, max_date):
    """
    Drop the leading and trailing weeks that the data only partly covers.

    A boundary week is partial when it starts before the first sale date, or
    ends after the last one — the raw units in it are real but the week is not
    a full week of selling, so it reads as an artificial dip.

    Returns (weekly_trimmed, grid, dropped_weeks).
    """
    observed = sorted({wk for _, _, _, wk in weekly})
    first_sale = date.fromisoformat(min_date)
    last_sale = date.fromisoformat(max_date)

    dropped = []
    first_wk, last_wk = observed[0], observed[-1]
    if first_wk < first_sale:
        dropped.append(first_wk)
        first_wk = first_wk + timedelta(days=7)
    if last_wk + timedelta(days=6) > last_sale:
        dropped.append(last_wk)
        last_wk = last_wk - timedelta(days=7)

    grid = week_grid(first_wk, last_wk)
    keep = set(grid)
    trimmed = {k: v for k, v in weekly.items() if k[3] in keep}
    return trimmed, grid, dropped


def zero_fill(weekly, grid):
    """
    Expand each series to one entry per week from its first sale week through
    the end of the grid, with 0 units in the weeks it did not sell.

    Weeks before a series' first sale are left out rather than zeroed — no
    sales there means the product was not yet stocked, not that demand was 0.

    Returns {(location_id, store_name, upc): {week: units}}.
    """
    observed = defaultdict(dict)
    for (loc, store, upc, wk), units in weekly.items():
        observed[(loc, store, upc)][wk] = units

    filled = {}
    for series, weeks in observed.items():
        start = min(weeks)
        filled[series] = {wk: weeks.get(wk, 0) for wk in grid if wk >= start}
    return filled


def build_dataset(sb, verbose=True):
    """
    Full prep pipeline: aggregate → trim partial weeks → zero-fill.

    Returns (filled, grid) for downstream modelling. Read-only.
    """
    weekly, min_date, max_date = aggregate_weekly(sb, verbose=verbose)
    trimmed, grid, dropped = trim_partial_weeks(weekly, min_date, max_date)
    filled = zero_fill(trimmed, grid)
    return filled, grid, dropped, weekly, min_date, max_date


def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("── Forecast Prep: weekly demand dataset ─────────────────────────────\n")

    filled, grid, dropped, raw, min_date, max_date = build_dataset(sb)

    raw_series = {(loc, store, upc) for loc, store, upc, _ in raw}
    raw_weeks = sorted({wk for _, _, _, wk in raw})

    print("── Raw aggregation ──────────────────────────────────────────────────\n")
    print(f"  Weekly rows (store × upc × week):  {len(raw):,}")
    print(f"  Distinct (store, upc) series:      {len(raw_series):,}")
    print(f"  Sale date range:                   {min_date} .. {max_date}")
    print(f"  Week range (Monday starts):        {raw_weeks[0]} .. {raw_weeks[-1]}"
          f"  ({len(raw_weeks)} weeks)")

    print("\n── Partial weeks dropped ────────────────────────────────────────────\n")
    for wk in dropped:
        print(f"  {wk}  (week not fully covered by the sale date range)")

    filled_rows = sum(len(w) for w in filled.values())
    lost = len(raw_series) - len(filled)

    print("\n── Zero-filled dataset ──────────────────────────────────────────────\n")
    print(f"  Weekly rows (store × upc × week):  {filled_rows:,}")
    print(f"  Distinct (store, upc) series:      {len(filled):,}")
    print(f"  Week range (Monday starts):        {grid[0]} .. {grid[-1]}"
          f"  ({len(grid)} weeks)")
    if lost:
        print(f"  Series dropped entirely:           {lost:,}"
              f"  (sold only in the partial weeks)")

    nonzero = sum(1 for w in filled.values() for u in w.values() if u)
    print(f"  Non-zero weeks:                    {nonzero:,}"
          f"  ({100 * nonzero / filled_rows:.1f}% of rows)")

    print("\n✅  Dataset built in memory. Nothing written to the DB.")


if __name__ == "__main__":
    main()
