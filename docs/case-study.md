# Building a Data Platform for a Wholesale Distribution Business — a 16-week internship.

A regional wholesale distributorship carrying the Little Debbie / McKee Foods line runs four delivery routes across roughly a hundred storefronts — grocery chains, dollar stores, convenience stores, gas stations. Over sixteen weeks I built the data platform it did not have: an ingestion pipeline with hard quality gates, a ten-page analytics dashboard, a demand forecasting model at store-SKU grain, and an AI drafting tool that turns next week's forecast into reorder reminders for the owner to review and send.

This is a write-up for an outside reader. It includes the numbers that did not hit their target and why, because those are the parts I learned the most from.

---

## The problem

Four routes. About 107 stores, 224 products, and eighteen months of invoice history — all of it living in two places: paper, and one-off report exports from Incorta, the supplier's reporting portal.

The portal answers the questions it was designed to answer. It does not answer the ones the business actually has:

- Which stores have quietly stopped buying, and how would anyone notice?
- Which products are declining on a route versus declining everywhere?
- What should each store be ordering next week?
- Where is promotional spend going, and is any of it unusual?

There was no unified data. Nothing joined invoices to orders to the store roster. Every question required someone to pull a report, open it in a spreadsheet, and reason about it by hand — which meant, in practice, that most of the questions simply went unasked. Churn in particular was invisible: a store that stopped ordering just stopped appearing, and nothing surfaced the absence.

The constraint that shaped everything: **there is no API into the source system.** Data arrives as manual CSV exports. Any platform built on top of it has to assume a human-in-the-loop refresh and be honest about staleness rather than pretend to be live.

---

## What was built

### 1. Ingestion pipeline with quality gates

Five hand-exported CSVs → a five-table Postgres schema on Supabase (`routes`, `products`, `stores`, `invoice_lines`, `order_lines`). Products and stores upsert; the two line tables are cleared and fully reloaded, because each export is a complete re-pull rather than an increment.

The interesting part is not the load, it is the **gate**. Verification is split in two:

- **Hard gate — internal consistency.** Did what we read out of the CSVs land in the database intact? Row counts CSV-vs-DB for both line tables, coverage checks on the upserted tables, sums of units / wholesale dollars / cases / cost compared CSV-vs-DB, zero NULL transaction types, store name present on every row. Any failure exits non-zero.
- **Informational — drift against the last blessed load.** A fresh export is *supposed* to differ from the previous one, so gating on it would fail every legitimate refresh.

A separate `quality_check.py` validates the loaded data without touching it: referential integrity on every UPC, route ID validity, transaction-type and date-range validity, unit-sign consistency, exact duplicates, and — added after the incident in Lessons §1 — a **scan-coverage check** that proves pagination reached the end of the table before anything downstream is trusted.

### 2. Ten-page analytics dashboard

Next.js on Vercel, reading Supabase Postgres. Pages: Overview, Stores, Store 360 (per-store detail), Products, Routes, Churn, Declining Products, Promotions, Forecasts, Reminders.

Two design decisions worth naming:

**The dashboard does not write SQL.** Every non-trivial query is a Postgres function (RPC) — thirteen of them — called from a React server component. Aggregation happens next to the data, page code stays a rendering concern, and the function definitions are exported to a checked-in `.sql` file so the analytical layer is reviewable as code.

**Churn logic lives in one shared module.** Early on, `/churn` and Store 360 each implemented their own churn rule and disagreed about a store. Both now import the same function, so they cannot diverge again.

That churn rule came out of a validation exercise rather than a whiteboard. I built a call sheet of flagged stores and had the owner check them against reality: **7 of 8 correct, 87.5% precision** — and the one miss was the most expensive account on the sheet, a live customer 29 days silent that a ratio-only threshold would have written off. The exercise produced something better than the score: an explicit business rule. *No sale in roughly 60 days means the store is churned and gets cut off; win-backs are not pursued.* Encoding that rule emptied the dashboard's "insufficient history" bucket entirely — three stores silent for 61, 77 and 137 days had been rendered grey and unactionable because they had too few orders to compute a cadence. The owner's rule needs no cadence.

### 3. Demand forecasting at store-SKU grain

One row per (store, product, week). XGBoost regressor over lag and trailing-window features, evaluated against a trailing-4-week-mean baseline on an 8-week holdout.

The honest headline: **60.0% WAPE, against a 64.4% baseline, at 0.7% of demand missed to stockout.** The section below explains why that number is what it is, and why the target it was measured against turned out to be the wrong target.

### 4. Claude-API reorder reminders, human-in-the-loop

The forecast is only useful if it reaches a decision. The reminder tool reads next week's forecast, keeps the stores forecast at **≥10 units**, takes each one's top 5 products, and asks Claude for a short, SMS-length message naming two or three of them and asking whether the store wants its regular delivery. Each is saved as a **draft**.

The lifecycle is `draft → approved → sent`, and the owner drives all of it — reviewing on the dashboard, approving, copying the text, sending from a personal phone, then marking it sent.

**Nothing in the system contacts a customer.** There is no phone number in the schema, no SMS integration, no auto-send. "Mark sent" records a fact; it delivers nothing. That is a deliberate default while draft quality is unproven — the failure mode of a bad automated message to a customer is worse than the cost of sending by hand.

The three status counts are also the product's **only honest impact measure**. `draft → approved` measures whether the model writes messages the owner would stand behind. `approved → sent` measures whether the workflow fits the day. A tool that drafts sixty messages and results in four sent is not a tool that needs more drafts.

Model settings were chosen, not defaulted: extended thinking off and effort low, because this is short-form generation rather than reasoning; `max_tokens` at 512 rather than something roomy, because the deliverable is under 400 characters and a large budget would hide a runaway response instead of surfacing it. Over-length drafts get exactly one corrective retry — a retry loop on a paid API call is its own hazard, so the second attempt is kept and counted either way. Upserts are per store rather than batched, so a crash at store 50 does not discard 49 drafts already paid for.

### 5. GitHub Actions automation

The first real use surfaced an operational gap that no amount of draft-quality work would have fixed: the Monday routine assumed fresh drafts, and nothing produced them. If neither script ran, the reminders page still rendered — serving last week's drafts with no indication they were stale.

A scheduled workflow now runs the forecast publish and the drafting step weekly, in that order, with concurrency set to queue rather than cancel (the drafting job upserts per store and has already paid for that work), and a hard stop if the forecast step fails — better no new drafts than drafts built on a stale forecast.

---

## Honest numbers, with context

### Scale

| | |
|---|---|
| Invoice line rows | **139,102** (124,472 of them Sales) |
| Order line rows | 23,644 |
| Stores / products / routes | 107 / 224 / 4 |
| Weekly series after zero-fill | 4,660 across 84 weeks |
| Forecast rows published per week | 1,792 |
| Reminder drafts per week | **63** (of 69 stores; 6 fall below the 10-unit floor) |

### Forecast accuracy: 66% → 60% WAPE, and a target that was re-scoped

The first working model, on the May export, scored **62.4% WAPE against a 66.4% baseline**. The current model — *identical features, identical hyperparameters, identical seed* — scores **60.0% against a 64.4% baseline** on the August export.

Every point of that improvement came from more data, not from better modelling. The August export added 17% more rows and 12 more weeks. No loss function, feature, or architecture I tried moved the number that far.

The original target was **≤53% WAPE**. It was not met, and I stopped trying to meet it. The evidence that the gap is structural rather than a tuning problem:

1. **The loss sweep flattened.** WAPE across Tweedie variance powers: 60.9 → 60.2 → 60.0 → 60.0 → 59.6. Each step buys ≤0.4 points, and each is paid for in missed sales.
2. **The two-stage model, which directly attacks the zero/non-zero structure, could only buy WAPE with stockouts** — and even discarding 13.2% of real demand it reached only 56.0%, still three points short.
3. **Feature importance shows the model rediscovering the baseline.** The trailing-4-week mean leads at 0.343 gain; week-of-year at 0.081 never found real seasonality.

The cause is the grain. **53.9% of holdout points are zero.** At (store, SKU, week) resolution, a forecast is mostly predicting *whether a sale happens at all* — intermittent demand, where WAPE's denominator is dominated by weeks that are genuinely unpredictable at that resolution. The ≤53% figure was set before anyone knew the zero rate.

So the target was re-scoped on evidence, and the paths that would actually change the constraint were written down instead: coarser grain (store × category, or biweekly buckets), Croston-type methods that model demand size and inter-arrival interval separately, or reframing the target entirely as a classification-plus-quantile problem scored on stockout and carrying cost. Re-negotiating a number you were given is a real result when you can show *why* — but only if you show why.

One more figure matters more than WAPE: **missed-sales share fell from 2.5% (baseline) to 0.7%.** In a distribution business, that is the number attached to money.

### 63 drafts, and 5 real sends

First real use, one Monday. The owner opened the reminders page, reviewed 63 drafts, and sent messages.

**The table records 6 sends. The real number is 5.** The top five were approved in a single 20-second burst and are exactly the five largest stores by forecast, worked strictly top-down. A sixth row sits ten minutes earlier and is two orders of magnitude smaller — it reads as a first click to see what the button did, not a deliberate send. I flagged the discrepancy in the phase doc rather than quietly banking the larger number, because these counts are the measure of the entire phase and a baseline you inflated once is a baseline you cannot use.

What five sends actually tell us:

- **They covered 49.5% of forecast volume.** Five of 63 drafts reached half the predicted units. A small number of high-volume stores carries most of the book — worth knowing before optimizing draft quality across the long tail.
- **Approve and send happened in one sitting.** None of the six stopped at `approved`. The two-step lifecycle is recording state, not pacing work.
- **The owner would use it weekly, and sent the drafts without rewriting them.** The gap was not draft quality; it was that the tool never said *when* to use it. That became the documented Monday routine.
- **A known theoretical risk hit on day one.** Same-chain stores get near-identical drafts, because each is generated from the same prompt with a similar product list. Four of the five deliberate sends were same-chain — three of one grocery banner, two of one supercenter — all receiving near-copies, to the highest-value stores on the route. Across all 1,953 draft pairs, mean word overlap is 44%.

I would not describe 5 sends as adoption. I would describe it as one real data point, honestly recorded, against which the next one can be compared.

---

## Engineering lessons

### 1. A passing check can be a check that read 0.7% of the table

PostgREST caps a response at 1,000 rows no matter how wide a range you request. My pagination loop treated "returned fewer rows than requested" as end-of-table. It is not — it is the cap.

Every whole-table scan in the quality checker read the first page and stopped: **1,000 of 139,102 rows, 0.7%**. The checks built on it did not fail. They passed *vacuously*. Transaction-type validation saw only `['Sale']`, because the sale file loads first. The UPC-orphan check saw 48 of 222 UPCs. Duplicate detection had the same defect. Green across the board, verifying almost nothing.

The fix was two lines of loop logic — advance by rows actually returned, stop only on an empty page, order by a unique column so pages form a stable window. The lesson was not the fix. It was that **a validation suite needs to validate its own coverage.** There is now an explicit scan-coverage check that proves pagination reached the end of the table before any downstream check is trusted, and distinct counts are printed in the success messages so truncation is visible rather than silent.

A related trap in the same area: a CSV-vs-DB money comparison reported $1.16 of "data loss" that was pure rounding — the source carried up to 15 decimal places, the column stores 2, and Postgres rounds on insert. The check now rounds each CSV row to the column's scale (half-up, matching Postgres) before summing, so it verifies nothing was lost rather than demanding nothing was rounded. **Make the check assert the property you care about, not an accident of representation.**

### 2. Hardcoded verification goes stale, and stale verification lies quietly

This bit twice, in two different shapes.

**In the pipeline:** ingestion verification asserted hardcoded totals from a specific export. Every fresh export failed on numbers that were *supposed* to change — so the gate trained me to ignore it, which is worse than not having a gate. Splitting it into a hard internal-consistency gate plus an informational drift comparison fixed the incentive: the part that fails means something, and the part that changes every time does not block.

**In the UI:** four dashboard pages stated their coverage as literal text — "Jan 2025 – Jun 2026". The August reload moved the real range to August 2026, and every one of those pages silently mislabelled its own figures by two months. Nothing errored. Nothing turned red. The pages just quietly asserted the wrong period, which is exactly the failure mode a dashboard exists to prevent. They now read the range from the data on every request.

**Anything a system asserts about itself should be derived, not typed.** A hardcoded fact is a fact with an expiry date and no alarm attached.

(A smaller cousin of the same bug is still open and documented: the forecasts table holds two generations of rows under the same model version, because the upsert key includes the week but the version string does not record which training data produced it. Any consumer must filter on week. Writing that down as a known hazard was the honest move; bumping the version string on every reload is the durable one.)

### 3. Framework presets are a guess, and a guess is not a build config

The first Vercel deploy failed. The repository is Python at the root, with the Next.js app in a `dashboard/` subdirectory — the auto-detected framework preset builds from the repository root, where there is no Next.js app to find. The build error described the symptom (no framework detected / nothing to build), not the cause (it was looking in the wrong directory).

The fix is a one-line project setting: point the root directory at `dashboard/`. The lesson is that **zero-config tooling infers a convention, and a repository that houses a data pipeline and a web app together does not match the convention.** When a preset fails, the question is "what did it assume about my layout" — not "what is wrong with my code." I lost real time reading the app for a fault that was never in the app.

### 4. Choose the metric that can see the failure you care about

MAPE is undefined at zero, so on this dataset it can only be computed on the 46.1% of points with non-zero actuals. It therefore describes the *easier half of the data* and quietly excludes the hard half. Reporting MAPE 50.5% against a 53% target would have been a fabricated success — right number, wrong population.

WAPE keeps the zero weeks in the numerator where the error is real, and weights by volume so a 3-unit miss on a 100-unit week does not count the same as a 3-unit miss on a 4-unit week. Under zero-inflation, it is the only one of the two that is honest.

**Under zero-inflated data, a metric that skips zeros is not a conservative metric — it is a different question with the same name.**

### 5. The two-metric acceptance rule, and the model I refused

WAPE has a blind spot of its own: it scores a 5-unit under-forecast identically to a 5-unit over-forecast. In distribution those are not the same event — one is carrying cost, the other is a lost sale. So accuracy is paired with a second, asymmetric metric: **missed-sales share**, the percentage of real demand forecast to essentially zero.

> **The rule: a candidate must not regress on *either* WAPE or missed-sales share. A gain on one bought with a loss on the other is not an improvement and will not be accepted as one.**

The rule earned itself twice.

A two-stage hurdle model posted the best WAPE in the entire project — **56.0%, four points better than the accepted model, and within striking distance of the original target**. It got there by predicting away **13.2% of all holdout units**: 15,036 units of real demand forecast to zero, against 790. That is not a better forecast. It is a model declining to forecast half the book and being rewarded by a metric that cannot see the consequence. The threshold sweep made the trade explicit — WAPE gains decelerate at every step while stockouts accelerate.

Then it bit a plain single-stage model too. Tweedie 1.9 scores 59.6% WAPE, 0.4 points ahead of the accepted 1.7 — and more than doubles missed units, 1,656 against 790. On WAPE alone, 1.9 wins. Under the rule, it is a regression, and the 0.4-point edge does not buy acceptance.

The uncomfortable part is that **the rule cost me the target.** With a WAPE-only criterion I could have written "56.0% WAPE, target nearly met" and it would have been arithmetically true. The rule is what made that sentence unwriteable. Deciding the acceptance criterion *before* seeing which model wins is the only reason it held.

---

## Stack

**Data & pipeline** — Python 3.11, pandas, Supabase (managed Postgres), `supabase-py` / PostgREST, `python-dotenv`. Fully pinned dependencies including transitives.

**Modelling** — XGBoost (Tweedie objective), scikit-learn, NumPy. Custom weekly-grain dataset construction with per-series zero-fill, boundary-week trimming, and an eligibility screen; backtest harness with rolling one-step-ahead evaluation.

**AI** — Claude API (`claude-sonnet-4-6`) via the `anthropic` SDK. Constraint-driven system prompt, thinking off / low effort, capped output, single corrective retry, per-item error isolation.

**Web** — Next.js 16 (App Router, React 19 server components), TypeScript, Tailwind CSS 4, Recharts, `@supabase/ssr` for auth. Postgres RPCs as the analytical layer; middleware-protected routes with email/password auth; service-role key strictly server-side.

**Infrastructure** — Vercel (dashboard), GitHub Actions (weekly scheduled forecast + drafting), Supabase (database + auth).

**Practices** — Hard-gated ingestion with self-validating coverage checks; phase documentation recording rejected approaches and known limitations alongside results; acceptance criteria fixed before evaluation; human-in-the-loop as the default for anything customer-facing.

---

## What I would tell you about it in an interview

The forecast missed its target and I would lead with that, because the interesting work is in the *why*. Sixteen weeks in, the model that gets published is not the most accurate one I built — it is the most accurate one that does not quietly stop forecasting the products a delivery business makes money on. Choosing that, and being able to show the sweep that justifies it, is the part I would defend.

The rest of it comes down to one habit: **when a system tells you it is fine, ask what it actually checked.** A green quality suite reading 0.7% of a table, a dashboard confidently labelling the wrong two months, a 56% WAPE bought by throwing away an eighth of real demand — all three look like success from the outside. Finding them was a matter of not accepting the reassuring number at face value, and the durable fix in every case was to make the system prove its own coverage rather than assert it.
