#!/usr/bin/env python3
"""
scripts/ingest.py
-----------------
Load products, stores, invoice_lines, order_lines into Supabase.
Safely re-runnable: products/stores use upsert; line tables are cleared then inserted.

Load order: products → stores → invoice_lines → order_lines

Verification is in two parts. Internal consistency is a hard gate: what the
CSVs contain must be exactly what landed in the DB. The comparison against the
previous load is INFO only — a fresh export is *supposed* to differ from the
last one, so gating on it would fail every legitimate refresh.
"""

import csv
import os
import sys
from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# ── Config ───────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]
BATCH_SIZE = 1000

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

# Totals from the last blessed load (May 2026 export). Reference points for the
# INFO comparison only — never a pass/fail gate. A fresh export legitimately
# differs, and gating on these made every refresh fail. Update when a load is
# reviewed and blessed.
PREVIOUS_LOAD = {
    "products": 218,
    "stores": 103,
    "invoice_rows": 119015,
    "invoice_units": 1352000,
    "invoice_dollars": 2797507.0,
    "order_rows": 20781,
    "order_cases": 98891,
    "order_cost": 2498556.0,
}

# Money columns are stored at 2 decimal places. orders.csv carries up to 15,
# so Postgres rounds every row on insert — the CSV must be rounded the same way
# before summing or the comparison reports a mismatch that is not a data loss.
DB_MONEY_SCALE = 2

# Remaining slack is float accumulation noise in the client-side DB sum only.
MONEY_TOLERANCE = 0.01
PAGE_SIZE = 1000


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
    for invoice_file in ("invoices_sale.csv", "invoices_return.csv", "invoices_buyback.csv"):
        with open(os.path.join(DATA_DIR, invoice_file), newline="", encoding="utf-8-sig") as f:
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

    invoice_files = [
        ("invoices_sale.csv",    "Sale"),
        ("invoices_return.csv",  "Return"),
        ("invoices_buyback.csv", "Buyback"),
    ]

    rows = []
    for filename, transaction_type in invoice_files:
        with open(os.path.join(DATA_DIR, filename), newline="", encoding="utf-8-sig") as f:
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
                        "transaction_type": transaction_type,
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
def money_sum(values):
    """
    Sum CSV money values the way Postgres stores them: round each row to the
    column's scale first, then add.

    orders.csv carries up to 15 decimal places on Total Cost while the column
    holds 2, so Postgres rounds 10,415 of 23,644 rows on insert. Summing the raw
    CSV values and comparing would flag ~$1.16 of accumulated rounding as a
    mismatch when every row landed exactly as the schema allows. ROUND_HALF_UP
    matches Postgres numeric rounding rather than Python's banker's rounding.
    """
    q = Decimal(10) ** -DB_MONEY_SCALE
    total = Decimal(0)
    for v in values:
        if v is not None:
            total += Decimal(str(v)).quantize(q, rounding=ROUND_HALF_UP)
    return float(total)


def fetch_sums(sb, table, columns):
    """
    Sum numeric columns straight from the DB, paginated.

    Ordered by id so the pages form a stable window — an unordered .range() can
    repeat or skip rows, which would silently corrupt the totals this check
    depends on.
    """
    totals = {c: 0 for c in columns}
    offset = 0
    while True:
        r = (
            sb.table(table)
            .select(",".join(columns))
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        for row in r.data:
            for c in columns:
                if row[c] is not None:
                    totals[c] += row[c]

        # Advance by what the server actually returned, and stop only on an
        # empty page. PostgREST caps responses (currently 1,000 rows) below
        # whatever PAGE_SIZE asks for, so "returned fewer than requested"
        # does NOT mean "end of table" — treating it that way silently sums
        # only the first page.
        if not r.data:
            break
        offset += len(r.data)
    return totals


def verify(sb, products, stores, invoice_rows, order_rows):
    """
    Hard-gate internal consistency; report drift from the previous load as INFO.

    The gate answers one question only: did what we read out of the CSVs land
    in the DB intact? It deliberately says nothing about whether the totals look
    like last time — that is what the INFO block is for.
    """
    print("\n── Verification: internal consistency (hard gate) ────────────────────\n")
    failures = []

    def check(label, ok, detail):
        if ok:
            print(f"  OK    {label}: {detail}")
        else:
            print(f"  FAIL  {label}: {detail}")
            failures.append(f"{label}: {detail}")

    # ── Row counts: CSV in == DB out ──────────────────────────────────────

    inv_db = sb.table("invoice_lines").select("id", count="exact").execute().count
    check(
        "invoice_lines row count",
        inv_db == len(invoice_rows),
        f"{len(invoice_rows):,} parsed from CSV, {inv_db:,} in DB",
    )

    ord_db = sb.table("order_lines").select("id", count="exact").execute().count
    check(
        "order_lines row count",
        ord_db == len(order_rows),
        f"{len(order_rows):,} parsed from CSV, {ord_db:,} in DB",
    )

    # products/stores are upserted, not cleared, so the DB may legitimately hold
    # rows from earlier loads. The requirement is coverage, not equality.
    db_upcs = {r["upc"] for r in sb.table("products").select("upc").execute().data}
    csv_upcs = {p["upc"] for p in products}
    missing_upcs = csv_upcs - db_upcs
    check(
        "products coverage",
        not missing_upcs,
        f"{len(csv_upcs):,} UPCs in CSV, {len(db_upcs):,} in DB, "
        f"{len(missing_upcs)} missing"
        + (f": {sorted(missing_upcs)[:5]}" if missing_upcs else ""),
    )

    db_stores = {
        (r["location_id"], r["store_name"], r["store_number"])
        for r in sb.table("stores")
        .select("location_id,store_name,store_number")
        .execute()
        .data
    }
    csv_stores = {
        (s["location_id"], s["store_name"], s["store_number"]) for s in stores
    }
    missing_stores = csv_stores - db_stores
    check(
        "stores coverage",
        not missing_stores,
        f"{len(csv_stores)} in CSV, {len(db_stores)} in DB, "
        f"{len(missing_stores)} missing"
        + (f": {sorted(missing_stores)[:3]}" if missing_stores else ""),
    )

    # ── Sums: CSV == DB ───────────────────────────────────────────────────

    inv_csv_units = sum(r["units"] for r in invoice_rows)
    inv_csv_dollars = money_sum(r["total_wholesale_dollars"] for r in invoice_rows)
    inv_sums = fetch_sums(sb, "invoice_lines", ["units", "total_wholesale_dollars"])

    check(
        "invoice_lines sum(units)",
        inv_sums["units"] == inv_csv_units,
        f"CSV {inv_csv_units:,} vs DB {inv_sums['units']:,}",
    )
    d = abs(float(inv_sums["total_wholesale_dollars"]) - inv_csv_dollars)
    check(
        "invoice_lines sum(wholesale $)",
        d <= MONEY_TOLERANCE,
        f"CSV ${inv_csv_dollars:,.2f} vs DB "
        f"${float(inv_sums['total_wholesale_dollars']):,.2f}  (Δ ${d:,.4f})",
    )

    ord_csv_cases = sum(r["cases_ordered"] or 0 for r in order_rows)
    ord_csv_cost = money_sum(r["total_cost"] for r in order_rows)
    ord_sums = fetch_sums(sb, "order_lines", ["cases_ordered", "total_cost"])

    check(
        "order_lines sum(cases_ordered)",
        ord_sums["cases_ordered"] == ord_csv_cases,
        f"CSV {ord_csv_cases:,} vs DB {ord_sums['cases_ordered']:,}",
    )
    d = abs(float(ord_sums["total_cost"]) - ord_csv_cost)
    check(
        "order_lines sum(total_cost)",
        d <= MONEY_TOLERANCE,
        f"CSV ${ord_csv_cost:,.2f} vs DB ${float(ord_sums['total_cost']):,.2f}"
        f"  (Δ ${d:,.4f})",
    )

    # ── Required fields ───────────────────────────────────────────────────

    tt_null = (
        sb.table("invoice_lines")
        .select("id", count="exact")
        .is_("transaction_type", "null")
        .execute()
        .count
    )
    check("transaction_type not null", tt_null == 0, f"{tt_null} NULL rows")

    sn_null = (
        sb.table("invoice_lines")
        .select("id", count="exact")
        .is_("store_name", "null")
        .execute()
        .count
    )
    sn_empty = (
        sb.table("invoice_lines")
        .select("id", count="exact")
        .eq("store_name", "")
        .execute()
        .count
    )
    check(
        "store_name present",
        sn_null + sn_empty == 0,
        f"{sn_null} NULL, {sn_empty} empty",
    )

    # ── INFO: this load vs the previous one ───────────────────────────────

    print("\n── INFO: totals vs previous load (not a gate) ────────────────────────\n")

    null_rows = [r for r in invoice_rows if r["store_id"] is None]
    null_dollars = money_sum(r["total_wholesale_dollars"] for r in null_rows)

    current = {
        "products": len(db_upcs),
        "stores": len(db_stores),
        "invoice_rows": inv_db,
        "invoice_units": inv_csv_units,
        "invoice_dollars": inv_csv_dollars,
        "order_rows": ord_db,
        "order_cases": ord_csv_cases,
        "order_cost": ord_csv_cost,
    }

    print(f"  {'metric':<20}{'previous':>16}{'this load':>16}{'change':>14}")
    for key, prev in PREVIOUS_LOAD.items():
        now = current[key]
        pct = 100 * (now - prev) / prev if prev else 0.0
        money = "dollars" in key or "cost" in key
        fmt = (lambda v: f"${v:,.0f}") if money else (lambda v: f"{v:,}")
        print(f"  {key:<20}{fmt(prev):>16}{fmt(now):>16}{pct:>13.1f}%")

    pct_rows = 100 * len(null_rows) / len(invoice_rows) if invoice_rows else 0
    pct_dollars = 100 * null_dollars / inv_csv_dollars if inv_csv_dollars else 0
    print(f"\n  NULL store_id: {len(null_rows):,} rows "
          f"({pct_rows:.1f}% of rows, {pct_dollars:.1f}% of wholesale $)"
          f"  — known limitation")

    print("\n  A fresh export is expected to differ here. Review the changes for"
          "\n  plausibility; update PREVIOUS_LOAD once this load is blessed.")

    # ── Result ────────────────────────────────────────────────────────────

    print()
    if failures:
        print("⛔  VERIFICATION FAILED — the DB does not match the CSVs")
        for f in failures:
            print(f"    {f}")
        print("    Investigate before trusting this load.")
        sys.exit(1)
    else:
        print("✅  ALL CONSISTENCY CHECKS PASSED")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Loading: products → stores → invoice_lines → order_lines\n")

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    products = load_products(sb)
    stores = load_stores(sb)
    invoice_rows = load_invoice_lines(sb)
    order_rows = load_order_lines(sb)

    verify(sb, products, stores, invoice_rows, order_rows)


if __name__ == "__main__":
    main()
