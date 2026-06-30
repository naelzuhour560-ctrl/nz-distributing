# Phase 1: Data Foundation

Technical documentation for Phase 1 of the N&Z Distributing data pipeline. This phase covers data sourcing, schema design, the ingestion script, and verification. Everything described here is implemented and running.

---

## 1. Data Sources

All source data comes from Incorta, the reporting platform used by McKee Foods / Little Debbie. Data is exported manually as CSV files and placed in the `data/` directory (gitignored).

### Invoice data — three filtered exports

The original Incorta invoice report contains a Transaction Type column with three values: Sale, Return, and Buyback. Rather than exporting a single file and parsing that column, we export three separate CSVs, each pre-filtered to one Transaction Type. The pipeline assigns `transaction_type` based on which file a row comes from.

| File | Transaction Type | Rows (current load) |
|---|---|---|
| `invoices_sale.csv` | Sale | 106,867 |
| `invoices_return.csv` | Return | 11,698 |
| `invoices_buyback.csv` | Buyback | 450 |
| **Total** | | **119,015** |

Why three files instead of one? The Incorta invoice export did not originally include the Transaction Type column. Rather than re-engineer the export to add it, we run three filtered exports — same 9 columns, same date range (1/1/2025 → today), different Transaction Type filter. This avoids any ambiguity about which rows are sales vs returns vs buybacks.

All three files share the same 9 columns:

```
Calendar Date, Location ID, Store Name, Invoice number, UPC,
Units, Distributor Unit Cost, Total Promotion Allowance, Total Wholesale Dollars
```

The `UPC` column in invoices is a compound field: `"83561 - Oatmeal Creme Pie"`. The pipeline splits on `" - "` to extract the bare numeric code (left side) and the product description (right side). The bare code matches the `UPC` column in orders, which carries just the number.

### Order data

| File | Rows (current load) |
|---|---|
| `orders.csv` | 20,781 |

11 columns: `Order Number, Delivery Date, Location ID, UPC, Product Name, SRP, Unit Cost, Case Cost, Cases Ordered, Cases Shipped, Total Cost`. The `UPC` here is the bare numeric code. `Product Name` is a separate column.

### Store roster

| File | Rows (current load) |
|---|---|
| `last_sold.csv` | 103 |

5 columns: `Location ID, Store Name, Store #, Store Address, Last Sold Date`. One row per physical store location across all 4 routes.

### CSV encoding

All Incorta exports are UTF-8 with a byte-order mark (BOM). The pipeline opens every CSV with `encoding="utf-8-sig"` to strip the BOM. Without this, Python's `csv.DictReader` embeds the BOM in the first column name, causing `KeyError` on field access.

---

## 2. Supabase Schema

Five tables in a single Supabase (managed Postgres) project.

### `routes`

| Column | Type | Notes |
|---|---|---|
| `location_id` | integer | **PK**. Natural key from Incorta; used as FK across all other tables |

4 rows, one per delivery route. Not managed by the ingestion script — populated manually in Supabase.

### `products`

| Column | Type | Notes |
|---|---|---|
| `upc` | text | **PK**. The bare numeric product code, stored as text |
| `product_name` | text | NOT NULL |
| `product_line` | text | Nullable, currently NULL for all rows |

218 rows. Built from the union of codes across all three invoice files and `orders.csv`. When a code appears in both sources, `product_name` is taken from the orders `Product Name` column (it tends to be more consistently formatted). Codes that appear only in invoices use the description parsed from the invoice `UPC` field.

Upserted on `upc` — safe to re-run.

### `stores`

| Column | Type | Notes |
|---|---|---|
| `store_id` | bigint | **PK** (surrogate, auto-increment) |
| `location_id` | integer | NOT NULL, FK → `routes` |
| `store_name` | text | NOT NULL |
| `store_number` | text | NOT NULL |
| `store_address` | text | Nullable |
| `last_sold_date` | date | Nullable |

103 rows. `UNIQUE(location_id, store_name, store_number)` — the composite natural key.

`store_number` is stored as text, carrying the chain store number where one exists.

Upserted on the composite unique constraint — safe to re-run.

### `invoice_lines`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint | **PK** (surrogate, auto-increment) |
| `invoice_number` | text | NOT NULL |
| `calendar_date` | date | NOT NULL, parsed from `%m/%d/%y` |
| `location_id` | integer | NOT NULL, FK → `routes` |
| `store_name` | text | NOT NULL, raw value from CSV — always populated |
| `store_id` | bigint | Nullable, FK → `stores` |
| `upc` | text | NOT NULL, FK → `products` (bare code, not the compound field) |
| `units` | integer | NOT NULL, may be negative (returns/buybacks) |
| `distributor_unit_cost` | numeric | Nullable |
| `total_promotion_allowance` | numeric | Nullable |
| `total_wholesale_dollars` | numeric | Nullable |
| `transaction_type` | text | NOT NULL in practice: `'Sale'`, `'Return'`, or `'Buyback'` |

119,015 rows. Cleared and fully reloaded on every run (delete where `id > 0`, then batch insert).

#### The store_id resolution problem

Invoice CSVs carry `Location ID` and `Store Name` but **not** `Store #`. The stores table is keyed on the triple `(location_id, store_name, store_number)`. When a `(location_id, store_name)` pair maps to exactly one store row, `store_id` is resolved. When it maps to multiple rows — because a chain has several locations on the same route under the same name — `store_id` is set to NULL.

This affects every major chain: Dollar General (up to 6 stores per route), Food Lion (2–3), Sheetz (2–3), Family Dollar (2), Walmart (2), GO MART (3). The result is 68,681 rows with NULL `store_id` — **57.7% of rows, 57.6% of wholesale dollars**.

`store_name` is always preserved on every invoice row regardless of whether `store_id` resolved, so the raw data is never lost.

### `order_lines`

| Column | Type | Notes |
|---|---|---|
| `id` | bigint | **PK** (surrogate, auto-increment) |
| `order_number` | text | NOT NULL |
| `delivery_date` | date | NOT NULL, parsed from `%m/%d/%y` |
| `location_id` | integer | NOT NULL, FK → `routes` |
| `upc` | text | NOT NULL, FK → `products` |
| `srp` | numeric | Nullable (suggested retail price) |
| `unit_cost` | numeric | Nullable |
| `case_cost` | numeric | Nullable |
| `cases_ordered` | integer | Nullable |
| `cases_shipped` | integer | Nullable |
| `total_cost` | numeric | Nullable |

20,781 rows. Cleared and fully reloaded on every run, same as invoice_lines.

---

## 3. Ingestion Pipeline

Single script: `scripts/ingest.py`. Reads credentials from `.env` via `python-dotenv`.

### Load order

Strict sequence — each step depends on the previous:

1. **Products** — must exist before invoice_lines or order_lines can reference them via FK
2. **Stores** — must exist before invoice_lines can look up `store_id`
3. **Invoice lines** — depends on products (FK) and stores (lookup)
4. **Order lines** — depends on products (FK)

### Upsert vs clear-reload

- **Products**: upsert on `upc`. New products are added; existing product names are updated. Safe for growing product catalogs.
- **Stores**: upsert on `(location_id, store_name, store_number)`. New stores are added; existing store addresses and last-sold dates are updated.
- **Invoice lines**: delete all (`id > 0`), then insert. Full reload every run. This is intentional — invoice data is a complete re-export from Incorta each time, not an incremental append.
- **Order lines**: same delete-all-then-insert pattern.

### Batching

All inserts and upserts are batched at 1,000 rows per API call (`BATCH_SIZE = 1000`). Progress is printed after each batch. At 119K invoice rows, this means ~119 API calls for that table.

### UPC parsing

Invoice CSVs encode the UPC as `"83561 - Oatmeal Creme Pie"`. The pipeline splits on `" - "` (space-dash-space) taking the left side as the bare code. This matches the bare numeric UPC in `orders.csv`. Both invoice and order UPCs share the same code space — 212 of 218 products appear in both sources.

### Store lookup

After loading stores, the pipeline fetches all `(store_id, location_id, store_name)` tuples from Supabase and builds an in-memory lookup dict keyed on `(location_id, store_name)`. If the pair maps to exactly one `store_id`, that value is used. If it maps to multiple (chain stores), the lookup returns `None` and `store_id` is inserted as NULL.

### Date parsing

All dates are parsed with `datetime.strptime(s, "%m/%d/%y")` and converted to ISO format (`YYYY-MM-DD`) for Postgres. The two-digit year `%y` handles the 2025–2026 range correctly.

---

## 4. Verification Checks

After loading all four tables, the script runs automated verification against hardcoded baselines. Each metric is checked independently; failures are collected and reported together.

| Check | Expected | What it guards |
|---|---|---|
| products row count | ~218 (±5) | No products lost or duplicated during upsert |
| stores row count | 103 | Store roster loaded completely |
| invoice_lines row count | 119,015 | All rows from all three CSV files loaded |
| invoice sum(units) | 1,352,000 | No rows silently dropped or double-counted |
| invoice sum(total_wholesale_dollars) | ≈$2,797,507 (±$500) | Financial totals match source data |
| invoice store_name nulls | 0 | store_name always preserved from CSV |
| order_lines row count | 20,781 | All order rows loaded |
| order sum(cases_ordered) | 98,891 | No order rows dropped |
| order sum(total_cost) | ≈$2,498,556 (±$500) | Order financial totals match source |

Row counts and unit sums use exact matching. Dollar totals allow ±$500 tolerance for floating-point accumulation across 100K+ rows. The NULL `store_id` count and percentage are reported for visibility but are not a pass/fail check (the NULL rate is a known consequence of the data, not a defect).

If any check fails, the script prints a `FAIL:` line for each failing metric with got/expected values, then exits with code 1. If all checks pass, it prints `ALL CHECKS PASSED` and exits with code 0.

Baselines must be updated manually in `ingest.py` when the source data grows (e.g., after a weekly re-export that adds new invoices). A baseline mismatch on a fresh export is expected and signals that you need to verify the new totals are correct, then update the baselines in the script.

### Data-quality checks (`scripts/quality_check.py`)

A standalone script that validates the loaded data without modifying it. Two severity levels:

**CRITICAL** (exit 1 if any fail):
- Every `invoice_lines.upc` and `order_lines.upc` exists in `products` (referential integrity)
- Every `location_id` in both line tables is in `{1483, 2140, 38260, 38265}`
- Every `invoice_lines.transaction_type` is `Sale`, `Return`, or `Buyback` with zero NULLs
- All `calendar_date` and `delivery_date` values fall within 2025-01-01 to today

**WARNING** (reported, does not affect exit code):
- Sale rows with negative units; Return or Buyback rows with positive units
- Exact-duplicate invoice rows (same invoice_number + upc + units + calendar_date)
- NULL `store_id` count and percentage

On the current load, all critical checks pass. The only warning is the known NULL `store_id` at 68,681 rows (57.7%).

---

## 5. Known Limitations

### NULL store_id (57.7% of invoice rows)

The Incorta invoice export does not include a store number. Chain stores with multiple locations on the same route share the same `(location_id, store_name)` pair, making unambiguous resolution to a single `store_id` impossible. This is a data source limitation, not a pipeline bug. Resolving it would require Incorta to include the store number in the invoice export.

### Manual export step

There is no API connection to Incorta. All CSV exports are performed manually through the Incorta web UI. The weekly ingestion process requires a human to run three filtered invoice exports, plus optionally the orders and store roster exports, then place the files in `data/` and run the script.

### Retention window

The current data covers January 2025 through May 2026 (~17 months). Each re-export from Incorta replaces the full date range; the pipeline does a full clear-and-reload, so there is no incremental history beyond what each export contains. If Incorta's retention window changes, historical data outside that window will be lost on the next reload.

### Verification baselines are static

The hardcoded baseline totals in `ingest.py` reflect a specific point-in-time export. When source data grows (new weeks of invoices), the verification will intentionally fail until baselines are updated. This is by design — it forces a human to confirm the new totals are correct before accepting them.
