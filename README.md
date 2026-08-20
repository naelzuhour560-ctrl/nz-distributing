# N&Z Distributing — Data Platform

## 1. What This Is

A data platform for a McKee Foods / Little Debbie wholesale distribution business running four delivery routes. It ingests the weekly Incorta exports into a Postgres database, serves them through a web dashboard covering revenue, stores, products, churn and promotions, forecasts next week's unit demand per store and product, and drafts a reorder reminder message for each store worth contacting. The forecasting and reminder drafting run on a schedule; the dashboard is read-only; every message that reaches a store is read and sent by a person. Nothing in this system contacts a customer on its own.

---

## 2. Architecture

```
  Incorta (McKee Foods reporting)
        │  5 manual CSV exports
        ▼
  data/*.csv  ──────────►  scripts/ingest.py  ──────────►  Supabase Postgres
   (gitignored)              clear + reload              routes, products, stores,
                             + verification              invoice_lines, order_lines
                                                                    │
                                    ┌───────────────────────────────┤
                                    │                               │
                                    ▼                               ▼
                        scripts/forecast_model.py          13 RPC functions
                         --write  (XGBoost)                (dashboard/sql/functions.sql)
                                    │                               │
                                    ▼                               ▼
                             forecasts table              Next.js dashboard
                                    │                     (Vercel) — read-only
                                    ▼                               ▲
                     scripts/generate_reminders.py                  │
                                    │                               │
                              Claude API                            │
                          (claude-sonnet-4-6)                       │
                                    │                               │
                                    ▼                               │
                             reminders table  ─────────────────────►┘
                                                              /reminders page
                                                        review → approve → mark sent

  .github/workflows/weekly-forecast.yml
    Mondays 10:00 UTC → forecast_model.py --write → generate_reminders.py
```

**Data flow in words.** Incorta CSVs are exported by hand and dropped in `data/`. `ingest.py` clears and reloads the line tables, then gates the load on CSV-vs-database consistency. The dashboard never queries tables directly for anything non-trivial — it calls Postgres functions (RPCs) whose definitions are exported to `dashboard/sql/functions.sql`. `forecast_model.py --write` trains on the full history and writes next week's per-store predictions to `forecasts`. `generate_reminders.py` reads those, keeps the stores worth contacting, and asks Claude for a short reorder message per store, saving each as a **draft**. The owner reviews drafts on `/reminders`. A GitHub Action runs the forecast and drafting steps weekly so the drafts are fresh without anyone running a script.

**Current scale**

| Table | Rows |
|---|---|
| `routes` | 4 |
| `products` | 224 |
| `stores` | 107 |
| `invoice_lines` | 139,102 |
| `order_lines` | 23,644 |
| `forecasts` | 1,792 |
| `reminders` | 63 |

---

## 3. Weekly Operations — Owner

**Monday, once a week. This is the whole job.**

1. Open the dashboard and go to **Reminders**.
2. Read the drafts. They are generated from the forecast and name the store's usual products.
3. **Approve** the ones worth sending.
4. **Copy** the message.
5. **Text** it to the store from your own phone.
6. **Mark sent.**

Nothing else is required. Drafts regenerate on their own each week — no script to run, no file to move.

Two things worth knowing:

- **The dashboard never sends anything.** "Mark sent" records that you sent it; it does not deliver a message. There is no phone number in the system.
- **Skipping a week costs nothing.** Drafts are overwritten each week, not queued. An unapproved draft simply disappears when the next week's batch replaces it.

The status counts on `/reminders` are the measure of whether this is working — see `docs/phase-4-reminders.md` §4.

---

## 4. Monthly-ish Operations — Maintainer

### 4.1 Refresh the source data

The database holds a snapshot. Refreshing it means re-exporting from Incorta and re-running the load.

**Export five files from Incorta.** All are UTF-8 with a BOM; the pipeline strips it. Date range on all invoice and order exports: **1/1/2025 → today**.

| Save as | Filter | Expected columns |
|---|---|---|
| `invoices_sale.csv` | Transaction Type = **Sale** | Calendar Date, Location ID, Store Name, Invoice number, UPC, Units, Distributor Unit Cost, Total Promotion Allowance, Total Wholesale Dollars |
| `invoices_return.csv` | Transaction Type = **Return** | *(same 9 columns)* |
| `invoices_buyback.csv` | Transaction Type = **Buyback** | *(same 9 columns)* |
| `orders.csv` | none | Order Number, Delivery Date, Location ID, UPC, Product Name, SRP, Unit Cost, Case Cost, Cases Ordered, Cases Shipped, Total Cost |
| `last_sold.csv` | none | Location ID, Store Name, Store #, Store Address, Last Sold Date |

The invoice report is exported **three times** with a different Transaction Type filter each time, rather than once with the column included. `ingest.py` assigns `transaction_type` from which file a row came from, so the filters are load-bearing: an unfiltered export saved as `invoices_sale.csv` would silently label returns as sales.

> **Gap:** the Incorta-side report/dashboard names are not recorded anywhere in this repo — only the resulting filenames and filters above. A maintainer who has not run this before will need someone to point them at the right Incorta reports. Worth writing down the next time it is done.

**Then move the files into `data/`** (gitignored — the exports never enter version control) and run, from the repo root:

```bash
source venv/bin/activate
python scripts/ingest.py         # clear + reload, then hard-gate on consistency
python scripts/quality_check.py  # referential integrity, ranges, duplicates
```

`ingest.py` **clears `invoice_lines` and `order_lines` before inserting**, so a failed or partial export leaves the tables empty. Check the CSV row counts look sane before running it.

Both scripts hard-fail on real problems and print an INFO comparison against the last blessed load — a fresh export is *expected* to differ, so drift there is informational, not an error. Once a load looks right, update `PREVIOUS_LOAD` in `ingest.py` to the new totals.

`data/returns_buybacks.csv` is a leftover from an earlier export scheme and is **not** read by anything.

### 4.2 After a data refresh

The forecast and reminders are built on the old snapshot until they are regenerated. Either wait for Monday's scheduled run, or force one:

```bash
python scripts/forecast_model.py --write     # must run first
python scripts/generate_reminders.py         # drafts from whatever --write published
```

Order matters — see `docs/phase-4-reminders.md` §6.

### 4.3 Keys and where they live

The same credentials are needed in four places. There is no shared secret store; each is set independently.

| Location | Keys | Used by |
|---|---|---|
| `.env` (repo root, gitignored) | `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `DB_PASSWORD`, `ANTHROPIC_API_KEY`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | every script in `scripts/` |
| `dashboard/.env.local` (gitignored) | `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `npm run dev` locally |
| Vercel project settings | same four as `.env.local` | the deployed dashboard |
| GitHub repository secrets | `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `ANTHROPIC_API_KEY` | the weekly Action |

`SUPABASE_SECRET_KEY` is the service-role key and bypasses row-level security. It is server-side only — it must never appear in a `NEXT_PUBLIC_*` variable or anywhere the browser can read.

`DB_PASSWORD` is for direct Postgres access, needed only to re-export `dashboard/sql/functions.sql`. Note that `db.<ref>.supabase.co` no longer resolves for this project; the working host is the newer pooler, `aws-1-us-east-1.pooler.supabase.com`, user `postgres.<project-ref>`.

### 4.4 Local setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cd dashboard && npm install && npm run dev
```

**On macOS, `import xgboost` fails after a clean install.** The wheel needs the OpenMP runtime, which is not a pip package. The Linux wheel bundles its own, so this affects local development only, never CI. See `docs/phase-3-baseline.md` §12 for the workaround and the permanent fixes.

### 4.5 Known operational gaps

- **The weekly Action is not live yet.** It requires a GitHub token with `workflow` scope to push, and the three repository secrets above to be set. Until both are done, drafts do not regenerate and `/reminders` will keep serving a stale week with no warning.
- **The Phase 1 base tables have no committed DDL.** `dashboard/sql/functions.sql` recreates the RPCs and the `forecasts`/`reminders` tables, but `routes`, `products`, `stores`, `invoice_lines` and `order_lines` exist only as prose in `docs/phase-1.md` §2. A true rebuild-from-scratch is not currently possible.

---

## 5. Repo Map

```
scripts/                  Python: ingest, quality, forecasting, reminders
  ingest.py               Incorta CSVs → Supabase; clears and reloads line tables
  quality_check.py        Referential integrity, ranges, duplicates, scan coverage
  forecast_prep.py        Weekly demand dataset (shared by the two below)
  forecast_baseline.py    Trailing-mean baseline — the bar the model must beat
  forecast_model.py       XGBoost backtest; --write publishes next week's forecast
  generate_reminders.py   Forecast → Claude API → reminder drafts

dashboard/                Next.js 16 app (Vercel)
  app/                    One directory per page; server components + RPC calls
  lib/                    Supabase clients (service-role, browser, auth) + shared helpers
  sql/functions.sql       Exported RPC definitions + forecasts/reminders DDL
  proxy.ts                Auth middleware — redirects anonymous traffic to /login

docs/                     Phase documentation and validation records
data/                     Incorta CSV exports (gitignored, never committed)
.github/workflows/        Weekly forecast + reminders automation
requirements.txt          Python dependencies, fully pinned
```

**Dashboard pages:** Overview, Stores (and per-store detail), Products, Routes, Churn, Declining, Promotions, Forecasts, Reminders.

---

## 6. Documentation Index

| Document | What it covers |
|---|---|
| [docs/phase-1.md](docs/phase-1.md) | **Data foundation.** Incorta sources and their quirks, the five-table Supabase schema, the ingestion pipeline, verification, and known limitations — including the NULL `store_id` problem that makes same-route chain stores indistinguishable. |
| [docs/phase-3-baseline.md](docs/phase-3-baseline.md) | **Forecasting.** Dataset construction, the trailing-mean baseline, the accepted model (tweedie 1.7, 60.0% WAPE / 0.7% missed units), the two-metric acceptance rule, why the original ≤53% target is unreachable at this grain, published-forecast handling, and the macOS libomp caveat. |
| [docs/phase-4-reminders.md](docs/phase-4-reminders.md) | **Reorder reminders.** What the tool drafts, the ≥10-unit floor, the draft→approved→sent lifecycle as the impact measure, the soft-launch results, and known limitations including near-duplicate drafts for same-chain stores. |
| [docs/churn-validation.md](docs/churn-validation.md) | **Churn validation.** The call sheet used to check churn flags against reality, the owner's 60-day cut-off rule that came out of it, the resulting precision, and what the exercise cannot measure. |

There is no Phase 2 document. Phase 2 was the dashboard pages themselves (Stores, Products, Routes, Churn, Declining, Promotions); its history is in the commit log rather than a write-up.
