# nz-distributing

Data engineering pipeline for N&Z Distributing, a McKee Foods / Little Debbie wholesale distributor operating 4 delivery routes across the Shenandoah Valley.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.9+ |
| Data processing | pandas, csv (stdlib) |
| Database | Supabase (managed Postgres) |
| ORM / client | supabase-py (postgrest) |
| Source data | Incorta CSV exports (invoices, orders, store roster) |

---

## Data Model

Five tables in Supabase:

| Table | Description |
|---|---|
| `routes` | The 4 distribution routes; `location_id` is the natural PK used across all other tables |
| `products` | One row per SKU; keyed on `upc` (text). Product name prefers orders export; falls back to invoice description for invoice-only codes |
| `stores` | All active stores; surrogate `store_id` PK with `UNIQUE(location_id, store_name, store_number)`. `store_number` stored as TEXT including `'0'` (used for independents with no chain store number) |
| `invoice_lines` | One row per invoice line item. Always carries `location_id` and `store_name`. `store_id` resolves only when `(location_id, store_name)` maps to exactly one store row — NULL otherwise (chains with multiple locations share the same name within a route) |
| `order_lines` | One row per order line item. Linked to `products` via `upc` and to `routes` via `location_id` |

---

## Data Foundation (current load)

| Table | Rows | Notes |
|---|---|---|
| products | 218 | Union of invoice and order SKUs |
| stores | 103 | All locations from last-sold roster |
| invoice_lines | 119,015 | Jan 2025 – May 2026; Sale / Return / Buyback |
| order_lines | 20,781 | Jan 2025 – May 2026 |

---

## Setup

```bash
git clone https://github.com/naelzuhour560-ctrl/nz-distributing.git
cd nz-distributing
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
SUPABASE_URL=...
SUPABASE_SECRET_KEY=...
```

Run the ingestion pipeline (safely re-runnable — products and stores upsert; line tables clear and reload):

```bash
python scripts/ingest.py
```

Source CSVs (`data/`) are gitignored and must be present locally.

---

## Weekly Ingestion

Each week, re-export the three invoice files from Incorta and re-run the pipeline.

### 1. Export from Incorta

Run three separate exports from the Incorta invoice report, each filtered by Transaction Type.
All three use the same date range (**1/1/2025 → today**) and the same 9 columns:
`Calendar Date, Location ID, Store Name, Invoice number, UPC, Units, Distributor Unit Cost, Total Promotion Allowance, Total Wholesale Dollars`

| Filter: Transaction Type | Save as |
|---|---|
| `Sale` | `data/invoices_sale.csv` |
| `Return` | `data/invoices_return.csv` |
| `Buyback` | `data/invoices_buyback.csv` |

Also re-export if the store roster or orders data has changed:
- `data/orders.csv` — full orders export (same date range)
- `data/last_sold.csv` — current store roster

### 2. Run the pipeline

```bash
source venv/bin/activate
python scripts/ingest.py
```

The script clears and reloads `invoice_lines` and `order_lines` on every run.
Products and stores are upserted (new rows added, existing rows updated).
Verification checks run automatically — if any baseline total is off, the script exits non-zero with a `FAIL` line for each mismatch.

### 3. Run data-quality checks (optional)

```bash
python scripts/quality_check.py
```

Checks referential integrity (UPCs exist in products), valid location IDs and transaction types, date range (2025-01-01 to today), unit-sign consistency (e.g. returns should not have positive units), exact-duplicate invoice rows, and NULL store_id rate. CRITICAL failures exit non-zero; warnings (like the known 57.7% NULL store_id) are reported but do not affect the exit code.

---

## Known Limitations

- **~57% of invoice rows have NULL `store_id`**: the Incorta invoice export does not include a store number, so any store name that belongs to a chain (Dollar General, Food Lion, Sheetz, etc.) with multiple locations on the same route cannot be unambiguously resolved to a single store.
- **`returns_buybacks.csv` not loaded**: superseded by the three filtered exports (`invoices_sale.csv`, `invoices_return.csv`, `invoices_buyback.csv`).

---

## Roadmap

| Phase | Status | Description |
|---|---|---|
| 1 — Foundation | ✅ Done | Schema design, CSV ingestion, Supabase load (119K invoice + 21K order rows) |
| 2 — Dashboards | Planned | Sales and inventory reporting by route, store, and product |
| 3 — Forecasting | Planned | Demand forecasting by SKU and store using historical invoice data |
| 4 — AI Automation | Planned | Route optimization, reorder suggestions, anomaly detection |
| 5 — Handoff | Planned | Documentation, operator training, and transition to production ownership |
