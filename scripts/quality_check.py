#!/usr/bin/env python3
"""
scripts/quality_check.py
------------------------
Standalone data-quality checks against loaded Supabase tables.
Reads .env for credentials. Does not modify any data.

Exit code 0 = no CRITICAL failures (warnings are OK).
Exit code 1 = one or more CRITICAL failures.
"""

import os
import sys
from datetime import date

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

VALID_LOCATION_IDS = {1483, 2140, 38260, 38265}
VALID_TRANSACTION_TYPES = {"Sale", "Return", "Buyback"}
DATE_FLOOR = "2025-01-01"


def fetch_distinct(sb, table, column):
    """Fetch all distinct values of a column, paginated."""
    values = set()
    offset = 0
    while True:
        r = sb.table(table).select(column).range(offset, offset + 4999).execute()
        for row in r.data:
            values.add(row[column])
        if len(r.data) < 5000:
            break
        offset += 5000
    return values


def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    criticals = []
    warnings = []

    print("── Data Quality Checks ──────────────────────────────────────────────\n")

    # ── Helpers ───────────────────────────────────────────────────────────

    def critical(label, detail):
        criticals.append(label)
        print(f"  FAIL  {label}: {detail}")

    def warn(label, detail):
        warnings.append(label)
        print(f"  WARN  {label}: {detail}")

    def ok(label):
        print(f"  OK    {label}")

    # ── Load reference sets ───────────────────────────────────────────────

    all_upcs = fetch_distinct(sb, "products", "upc")
    today = date.today().isoformat()

    # ── CRITICAL: invoice_lines.upc → products ───────────────────────────

    print("[CRITICAL] Referential integrity\n")

    inv_upcs = fetch_distinct(sb, "invoice_lines", "upc")
    orphan_inv = inv_upcs - all_upcs
    if orphan_inv:
        critical("invoice_lines.upc orphans", f"{len(orphan_inv)} UPCs not in products: {sorted(orphan_inv)[:10]}")
    else:
        ok("invoice_lines.upc — all UPCs exist in products")

    # ── CRITICAL: order_lines.upc → products ─────────────────────────────

    ord_upcs = fetch_distinct(sb, "order_lines", "upc")
    orphan_ord = ord_upcs - all_upcs
    if orphan_ord:
        critical("order_lines.upc orphans", f"{len(orphan_ord)} UPCs not in products: {sorted(orphan_ord)[:10]}")
    else:
        ok("order_lines.upc — all UPCs exist in products")

    # ── CRITICAL: invoice_lines.location_id valid ─────────────────────────

    print("\n[CRITICAL] Location ID validity\n")

    inv_locs = fetch_distinct(sb, "invoice_lines", "location_id")
    bad_loc_inv = inv_locs - VALID_LOCATION_IDS
    if bad_loc_inv:
        critical("invoice_lines.location_id", f"unknown location_ids: {sorted(bad_loc_inv)}")
    else:
        ok("invoice_lines.location_id — all valid")

    # ── CRITICAL: order_lines.location_id valid ──────────────────────────

    ord_locs = fetch_distinct(sb, "order_lines", "location_id")
    bad_loc_ord = ord_locs - VALID_LOCATION_IDS
    if bad_loc_ord:
        critical("order_lines.location_id", f"unknown location_ids: {sorted(bad_loc_ord)}")
    else:
        ok("order_lines.location_id — all valid")

    # ── CRITICAL: transaction_type values ─────────────────────────────────

    print("\n[CRITICAL] Transaction type integrity\n")

    r = sb.table("invoice_lines").select("id", count="exact").is_("transaction_type", "null").execute()
    null_tt = r.count
    if null_tt:
        critical("transaction_type NULL", f"{null_tt} invoice rows have NULL transaction_type")
    else:
        ok("transaction_type — zero NULLs")

    inv_tts = fetch_distinct(sb, "invoice_lines", "transaction_type")
    bad_tt = inv_tts - VALID_TRANSACTION_TYPES - {None}
    if bad_tt:
        critical("transaction_type invalid", f"unexpected values: {sorted(bad_tt)}")
    else:
        ok("transaction_type — all values are Sale, Return, or Buyback")

    # ── CRITICAL: date range ──────────────────────────────────────────────

    print("\n[CRITICAL] Date range (2025-01-01 to today)\n")

    r = sb.table("invoice_lines").select("id", count="exact").lt("calendar_date", DATE_FLOOR).execute()
    r2 = sb.table("invoice_lines").select("id", count="exact").gt("calendar_date", today).execute()
    inv_out = r.count + r2.count
    if inv_out:
        critical("invoice_lines.calendar_date", f"{inv_out} rows outside 2025-01-01..{today}")
    else:
        ok(f"invoice_lines.calendar_date — all within 2025-01-01..{today}")

    r = sb.table("order_lines").select("id", count="exact").lt("delivery_date", DATE_FLOOR).execute()
    r2 = sb.table("order_lines").select("id", count="exact").gt("delivery_date", today).execute()
    ord_out = r.count + r2.count
    if ord_out:
        critical("order_lines.delivery_date", f"{ord_out} rows outside 2025-01-01..{today}")
    else:
        ok(f"order_lines.delivery_date — all within 2025-01-01..{today}")

    # ── WARNING: unit sign vs transaction type ────────────────────────────

    print("\n[WARNING] Unit sign consistency\n")

    r = sb.table("invoice_lines").select("id", count="exact").eq("transaction_type", "Sale").lt("units", 0).execute()
    if r.count:
        warn("Sale with negative units", f"{r.count} Sale rows have units < 0")
    else:
        ok("Sale rows — all units >= 0")

    r = sb.table("invoice_lines").select("id", count="exact").eq("transaction_type", "Return").gt("units", 0).execute()
    if r.count:
        warn("Return with positive units", f"{r.count} Return rows have units > 0")
    else:
        ok("Return rows — all units <= 0")

    r = sb.table("invoice_lines").select("id", count="exact").eq("transaction_type", "Buyback").gt("units", 0).execute()
    if r.count:
        warn("Buyback with positive units", f"{r.count} Buyback rows have units > 0")
    else:
        ok("Buyback rows — all units <= 0")

    # ── WARNING: exact duplicate invoice rows ─────────────────────────────

    print("\n[WARNING] Duplicate detection\n")

    seen = {}
    offset = 0
    while True:
        r = sb.table("invoice_lines").select("invoice_number,upc,units,calendar_date").range(offset, offset + 4999).execute()
        for row in r.data:
            key = (row["invoice_number"], row["upc"], row["units"], row["calendar_date"])
            seen[key] = seen.get(key, 0) + 1
        if len(r.data) < 5000:
            break
        offset += 5000
    dupe_count = sum(v - 1 for v in seen.values() if v > 1)
    dupe_keys = sum(1 for v in seen.values() if v > 1)
    if dupe_count:
        warn("Duplicate invoice rows", f"{dupe_count} extra rows across {dupe_keys} duplicate keys (invoice_number + upc + units + calendar_date)")
    else:
        ok("No exact-duplicate invoice rows detected")

    # ── WARNING: NULL store_id ────────────────────────────────────────────

    print("\n[WARNING] NULL store_id\n")

    r_null = sb.table("invoice_lines").select("id", count="exact").is_("store_id", "null").execute()
    r_all = sb.table("invoice_lines").select("id", count="exact").execute()
    pct = 100 * r_null.count / r_all.count if r_all.count else 0
    warn("NULL store_id", f"{r_null.count:,} of {r_all.count:,} invoice rows ({pct:.1f}%) — known limitation, chain stores unresolvable")

    # ── Summary ───────────────────────────────────────────────────────────

    print("\n── Summary ──────────────────────────────────────────────────────────")
    print(f"   CRITICAL failures: {len(criticals)}")
    print(f"   Warnings:          {len(warnings)}")

    if criticals:
        print("\n⛔  QUALITY CHECK FAILED")
        for c in criticals:
            print(f"    - {c}")
        sys.exit(1)
    else:
        print("\n✅  ALL CRITICAL CHECKS PASSED")


if __name__ == "__main__":
    main()
