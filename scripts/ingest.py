#!/usr/bin/env python3
"""
scripts/ingest.py
-----------------
Load products, stores, invoice_lines, order_lines into Supabase.
Safely re-runnable: products/stores use upsert; line tables are cleared then inserted.

Schema note: invoice_lines has no store_name column in the DB.
The store_id NULL-resolution logic uses store_name from the CSV, but store_name
is NOT inserted (column doesn't exist). Add it via Supabase console if desired.

Load order: products → stores → invoice_lines → order_lines
"""

import csv
import os
import sys
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
BATCH_SIZE = 1000

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")


def parse_date(s):
    return datetime.strptime(s.strip(), "%m/%d/%y").date().isoformat()


def batched(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def float_or_none(s):
    s = s.strip()
    return float(s) if s else None


def int_or_none(s):
    s = s.strip()
    return int(s) if s else None


# ── 1. Products ───────────────────────────────────────────────────────────────
def load_products(sb):
    print("\n[1/4] Products")

    # Pass 1: invoice codes → description (first occurrence wins)
    invoice_desc = {}
    with open(os.path.join(DATA_DIR, "invoices.csv"), newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            upc_field = row["UPC"].strip()
            parts = upc_field.split(" - ", 1)
            code = parts[0].strip()
            desc = parts[1].strip() if len(parts) > 1 else upc_field
            if code not in invoice_desc:
                invoice_desc[code] = desc

    # Pass 2: order codes → Product Name (first occurrence wins, preferred)
    order_name = {}
    with open(os.path.join(DATA_DIR, "orders.csv"), newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = row["UPC"].strip()
            name = row["Product Name"].strip()
            if code not in order_name:
                order_name[code] = name

    # Union of all codes; prefer orders name, fall back to invoice description
    all_codes = set(invoice_desc.keys()) | set(order_name.keys())
    products = []
    for code in sorted(all_codes):
        name = order_name.get(code) or invoice_desc.get(code)
        products.append({"upc": code, "product_name": name, "product_line": None})

    total = len(products)
    upserted = 0
    for batch in batched(products, BATCH_SIZE):
        sb.table("products").upsert(batch, on_conflict="upc").execute()
        upserted += len(batch)
        print(f"  upserted {upserted}/{total}")

    return products


# ── 2. Stores ─────────────────────────────────────────────────────────────────
def load_stores(sb):
    print("\n[2/4] Stores")

    stores = []
    with open(os.path.join(DATA_DIR, "last_sold.csv"), newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            stores.append(
                {
                    "location_id": int(row["Location ID"].strip()),
                    "store_name": row["Store Name"].strip(),
                    "store_number": row["Store #"].strip(),  # TEXT, including '0'
                    "store_address": row["Store Address"].strip() or None,
                    "last_sold_date": parse_date(row["Last Sold Date"]),
                }
            )

    total = len(stores)
    upserted = 0
    for batch in batched(stores, BATCH_SIZE):
        sb.table("stores").upsert(
            batch, on_conflict="location_id,store_name,store_number"
        ).execute()
        upserted += len(batch)
        print(f"  upserted {upserted}/{total}")

    return stores


# ── Store lookup for invoice_lines ────────────────────────────────────────────
def build_store_lookup(sb):
    """
    Return dict: (location_id: int, store_name: str) → store_id (int) or None.
    None means the pair maps to >1 store — store_id must be NULL on invoice row.
    """
    result = sb.table("stores").select("store_id,location_id,store_name").execute()
    by_key = defaultdict(list)
    for s in result.data:
        by_key[(s["location_id"], s["store_name"])].append(s["store_id"])

    return {
        key: (ids[0] if len(ids) == 1 else None)
        for key, ids in by_key.items()
    }


# ── 3. Invoice Lines ──────────────────────────────────────────────────────────
def load_invoice_lines(sb):
    print("\n[3/4] Invoice lines")

    # Clear existing rows
    sb.table("invoice_lines").delete().gt("id", 0).execute()
    print("  cleared invoice_lines")

    store_lookup = build_store_lookup(sb)

    rows = []
    with open(os.path.join(DATA_DIR, "invoices.csv"), newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            upc_field = row["UPC"].strip()
            code = upc_field.split(" - ", 1)[0].strip()
            location_id = int(row["Location ID"].strip())
            store_name = row["Store Name"].strip()
            store_id = store_lookup.get((location_id, store_name))

            rows.append(
                {
                    "invoice_number": row["Invoice number"].strip(),
                    "calendar_date": parse_date(row["Calendar Date"]),
                    "location_id": location_id,
                    "store_name": store_name,
                    "store_id": store_id,
                    "upc": code,
                    "units": int(row["Units"].strip()),
                    "distributor_unit_cost": float_or_none(row["Distributor Unit Cost"]),
                    "total_promotion_allowance": float_or_none(row["Total Promotion Allowance"]),
                    "total_wholesale_dollars": float_or_none(row["Total Wholesale Dollars"]),
                    "transaction_type": None,
                }
            )

    total = len(rows)
    inserted = 0
    for batch in batched(rows, BATCH_SIZE):
        sb.table("invoice_lines").insert(batch).execute()
        inserted += len(batch)
        print(f"  inserted {inserted}/{total}")

    return rows


# ── 4. Order Lines ────────────────────────────────────────────────────────────
def load_order_lines(sb):
    print("\n[4/4] Order lines")

    sb.table("order_lines").delete().gt("id", 0).execute()
    print("  cleared order_lines")

    rows = []
    with open(os.path.join(DATA_DIR, "orders.csv"), newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(
                {
                    "order_number": row["Order Number"].strip(),
                    "delivery_date": parse_date(row["Delivery Date"]),
                    "location_id": int(row["Location ID"].strip()),
                    "upc": row["UPC"].strip(),
                    "srp": float_or_none(row["SRP"]),
                    "unit_cost": float_or_none(row["Unit Cost"]),
                    "case_cost": float_or_none(row["Case Cost"]),
                    "cases_ordered": int_or_none(row["Cases Ordered"]),
                    "cases_shipped": int_or_none(row["Cases Shipped"]),
                    "total_cost": float_or_none(row["Total Cost"]),
                }
            )

    total = len(rows)
    inserted = 0
    for batch in batched(rows, BATCH_SIZE):
        sb.table("order_lines").insert(batch).execute()
        inserted += len(batch)
        print(f"  inserted {inserted}/{total}")

    return rows


# ── Verification ──────────────────────────────────────────────────────────────
def verify(sb, invoice_rows, order_rows):
    print("\n── Verification ─────────────────────────────────────────────────────")
    stop = False

    def check(label, actual, expected, tolerance=0):
        nonlocal stop
        if tolerance:
            ok = abs(actual - expected) <= tolerance
        else:
            ok = actual == expected
        flag = "" if ok else "  ⚠ UNEXPECTED"
        if not ok:
            stop = True
        return flag

    # Products (DB count)
    r = sb.table("products").select("upc", count="exact").execute()
    n = r.count
    flag = check("products", n, 218, tolerance=5)
    print(f"products:      {n} rows  (expect ~218){flag}")

    # Stores (DB count)
    r = sb.table("stores").select("store_id", count="exact").execute()
    n = r.count
    flag = check("stores", n, 103)
    print(f"stores:        {n} rows  (expect 103){flag}")

    # Invoice lines — row count from DB; sums from in-memory rows
    r = sb.table("invoice_lines").select("id", count="exact").execute()
    inv_db_count = r.count
    flag_count = check("invoice_lines rows", inv_db_count, 118873)
    print(f"invoice_lines: {inv_db_count:,} rows  (expect 118,873){flag_count}")

    inv_units = sum(r["units"] for r in invoice_rows)
    flag_units = check("invoice units", inv_units, 1349561)
    print(f"               sum(units) = {inv_units:,}  (expect 1,349,561){flag_units}")

    inv_dollars = sum(r["total_wholesale_dollars"] or 0.0 for r in invoice_rows)
    flag_dollars = check("invoice dollars", inv_dollars, 2792886, tolerance=500)
    print(f"               sum(total_wholesale_dollars) = ${inv_dollars:,.2f}  (expect ≈$2,792,886){flag_dollars}")

    null_rows = [r for r in invoice_rows if r["store_id"] is None]
    null_count = len(null_rows)
    null_dollars = sum(r["total_wholesale_dollars"] or 0.0 for r in null_rows)
    pct_rows = 100 * null_count / len(invoice_rows) if invoice_rows else 0
    pct_dollars = 100 * null_dollars / inv_dollars if inv_dollars else 0
    print(
        f"               NULL store_id: {null_count:,} rows  "
        f"({pct_rows:.1f}% of rows, {pct_dollars:.1f}% of wholesale $)"
    )

    sn_nulls = sum(1 for r in invoice_rows if not r.get("store_name"))
    flag_sn = "" if sn_nulls == 0 else "  ⚠ UNEXPECTED"
    if sn_nulls: stop = True
    print(f"               store_name NULL/empty: {sn_nulls} rows  (expect 0){flag_sn}")

    # Order lines — row count from DB; sums from in-memory rows
    r = sb.table("order_lines").select("id", count="exact").execute()
    ord_db_count = r.count
    flag_count = check("order_lines rows", ord_db_count, 20781)
    print(f"order_lines:   {ord_db_count:,} rows  (expect 20,781){flag_count}")

    cases = sum(r["cases_ordered"] or 0 for r in order_rows)
    flag_cases = check("order cases", cases, 98891)
    print(f"               sum(cases_ordered) = {cases:,}  (expect 98,891){flag_cases}")

    ord_cost = sum(r["total_cost"] or 0.0 for r in order_rows)
    flag_cost = check("order cost", ord_cost, 2498556, tolerance=500)
    print(f"               sum(total_cost) = ${ord_cost:,.2f}  (expect ≈$2,498,556){flag_cost}")

    print()
    if stop:
        print("⛔  One or more verification totals are materially off.")
        print("    STOPPING — investigate before trusting this load.")
        sys.exit(1)
    else:
        print("✓  All verification checks passed.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Loading: products → stores → invoice_lines → order_lines\n")

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    load_products(sb)
    load_stores(sb)
    invoice_rows = load_invoice_lines(sb)
    order_rows = load_order_lines(sb)

    verify(sb, invoice_rows, order_rows)


if __name__ == "__main__":
    main()
