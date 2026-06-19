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
| invoice_lines | 118,873 | Jan 2025 – May 2026 |
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

## Known Limitations

- **~57% of invoice rows have NULL `store_id`**: the Incorta invoice export does not include a store number, so any store name that belongs to a chain (Dollar General, Food Lion, Sheetz, etc.) with multiple locations on the same route cannot be unambiguously resolved to a single store.
- **Transaction Type not yet captured**: the `transaction_type` column exists on `invoice_lines` but is left NULL pending a corrected data pull from Incorta that includes this field.
- **`returns_buybacks.csv` intentionally not loaded**: returns/buybacks data is present in `data/` but excluded from Phase 1 ingestion; it will be addressed in a later phase once the schema for that data is finalized.

---

## Roadmap

| Phase | Status | Description |
|---|---|---|
| 1 — Foundation | ✅ Done | Schema design, CSV ingestion, Supabase load (118K invoice + 21K order rows) |
| 2 — Dashboards | Planned | Sales and inventory reporting by route, store, and product |
| 3 — Forecasting | Planned | Demand forecasting by SKU and store using historical invoice data |
| 4 — AI Automation | Planned | Route optimization, reorder suggestions, anomaly detection |
| 5 — Handoff | Planned | Documentation, operator training, and transition to production ownership |
