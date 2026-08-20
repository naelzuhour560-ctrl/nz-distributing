# Phase 4: Reorder Reminders

Turns next week's forecast into a drafted reorder message per store, for the owner to read, approve, and send himself. Built by `scripts/generate_reminders.py` (drafting) and the `/reminders` page (review and approval).

**The tool drafts and tracks. It does not send.** Every message reaches a store because a person read it and sent it.

---

## 1. What It Does

1. Reads next week's forecast for every store.
2. Keeps stores forecast at **≥10 units** and takes each one's **top 5 products**.
3. Asks Claude for a short, friendly SMS-length reminder naming 2–3 of those products and asking whether they want their regular delivery.
4. Saves each as a **draft** in the `reminders` table.
5. The owner reviews them on `/reminders`, approves the ones he wants, sends them himself, and marks them sent.

The message is deliberately low-key: no prices, no discounts, no urgency, no upsell. It is a rep checking in, not a marketing blast. Those constraints are in the system prompt, not left to the model's judgement.

---

## 2. Architecture

```
forecast_next_week()          1,792 forecast rows for the week
        │
        ▼
generate_reminders.py         group by store → ≥10-unit floor → top 5 products
        │                     63 of 69 stores kept
        ▼
Claude API                    claude-sonnet-4-6, one call per store
        │                     thinking off · effort low · max_tokens 512
        ▼
reminders table               status 'draft', top_products JSON, forecast total
        │
        ▼
/reminders page               card per store → Approve → Mark sent
```

**Model settings are deliberate, not defaults.** Thinking is off and effort is `low`: this is short-form content generation, not reasoning, and that pairing is the documented setting for it — material across 63 calls. `max_tokens` is 512 rather than a roomy default because the deliverable is under 400 characters; a large budget would hide a runaway response instead of surfacing it.

**Over-length drafts get exactly one corrective retry**, shown their own draft and character count. 400 characters is an SMS constraint, so a long draft is unusable rather than untidy — but a retry loop on a paid API call is its own hazard, so the second attempt is kept and counted either way. In the current run no draft needed one: lengths came in at **190–275 characters**.

**Upserts are per store, not batched.** Each row costs an API call; a crash at store 50 should not discard 49 drafts already paid for. Failures are caught per store by typed exception, so one bad call cannot abandon the run.

The upsert key is `(location_id, store_name, week_start)`, so re-running for the same week overwrites that week's drafts rather than duplicating them.

---

## 3. The ≥10-Unit Floor

A store forecast under 10 units for the week does not get a message.

The reminder costs more than the API call: it costs the owner's attention to read and approve, the store's attention to read, and a small amount of the relationship if the messages feel like noise. A store expected to buy a handful of units is not worth spending any of that on — and a forecast that small is also the least reliable part of the model (`docs/phase-3-baseline.md` §8: the binding constraint at this grain is that demand is mostly intermittent).

Current effect: **63 of 69 stores** clear the floor, 6 do not. The smallest store that qualifies is `Circle K` at **10.15 units** — close enough to the line that the threshold is doing real work rather than sitting in dead space.

---

## 4. Status Lifecycle — the Impact Measure

```
draft ──Approve──▶ approved ──Mark sent──▶ sent
```

| Status | Means | Set by |
|---|---|---|
| `draft` | Model wrote it; nobody has read it | `generate_reminders.py` |
| `approved` | Owner read it and would send it (stamps `approved_at`) | `/reminders` → Approve |
| `sent` | Owner sent it to the store himself | `/reminders` → Mark sent |

**These three counts are the honest measure of whether the tool is worth anything.**

- **draft → approved** measures draft quality. If the owner approves most drafts, the model is writing messages he'd stand behind. If he rewrites or skips most, the prompt is wrong and the drafting is not earning its cost.
- **approved → sent** measures whether the workflow fits his day. Drafts approved but never sent mean the tool produces work he agrees with but does not act on — which is a failure of the tool, not of him.

Both ratios should be read before adding any feature to this phase. A tool that generates 63 drafts and results in 4 sent messages is not a tool that needs more drafts.

Note the asymmetry: `approved_at` is stamped, but there is **no `sent_at` column**, so time-to-send cannot be measured — only the final state. Add one before trying to measure workflow latency.

---

## 5. Known Limitations

### Sending is manual — by design, not by omission

Nothing in this repo can send a message to a store. There is no phone number in the schema, no SMS integration, no scheduled job. "Mark sent" records that the owner sent it himself; it delivers nothing.

This is the correct default while draft quality is unproven. An automated sender built on the same model would deliver every one of the near-duplicate drafts below, and the failure mode of a bad automated message to a customer is worse than the cost of sending by hand. Do not add auto-send until the draft→approved ratio in §4 justifies it.

### Near-duplicate drafts for same-chain stores

**Six store names appear on more than one route**, accounting for **20 of the 63 reminders**:

| Store name | Routes |
|---|---|
| DOLLAR GEN | 4 |
| FOOD LION | 4 |
| WALMART SUP | 4 |
| FAMILY DOL | 3 |
| SHEETZ | 3 |
| GO MART | 2 |

Because every draft is generated from the same prompt with a similar product list, these come back close to identical. Two of the four Food Lion drafts:

> Hey Food Lion! Hope y'all are having a good week. Just checking in — would you like your regular delivery of Oatmeal Creme Pies, Honey Buns, and Nutty Buddys this week? …

> Hey Food Lion! Hope y'all are doing well. Just checking in — would you like your regular order of Oatmeal Creme Pies, Honey Buns, and Nutty Buddys this week? …

Across **all 1,953 draft pairs** the mean word overlap is **44%** — the whole set shares one voice, which is fine, but the same-chain pairs are near-copies. They go to different physical stores, so duplication is not wrong on its face; the risk is that a recipient who compares notes with another location sees a form letter, which undercuts the "rep who knows you" tone the prompt is aiming for.

### Store names are truncated, and the model expands them inconsistently

The source data carries names like `FAMILY DOL`, `WALMART SUP`, `DOLLAR GEN` — truncated in the Incorta export. The model sometimes expands them and sometimes does not. Across the three `FAMILY DOL` drafts it opened with "Hey Family Dollar!" twice and "Hey Family Dol!" once.

"Hey Family Dol!" is going to a customer. **Fixing this belongs in the data, not the prompt** — a display-name column on `stores` would make every downstream use correct at once, where a prompt instruction only patches this one.

### One reminder can represent several physical stores

`docs/phase-1.md` records that 58.3% of invoice rows have a NULL `store_id`, so chain stores on the same route collapse into a single `(location_id, store_name)` row. "FOOD LION on route 1483" may be several physical Food Lions, and they share one forecast and one reminder. Whoever sends it needs to know which location they are talking to; the tool cannot tell them.

### Regeneration is manual, weekly

There is no scheduler. Each week the sequence is:

```
python scripts/forecast_model.py --write      # publish next week's forecast
python scripts/generate_reminders.py          # draft reminders from it
```

Running `generate_reminders.py` without a fresh `--write` first will redraft **the same week** — the upsert key includes `week_start`, so it overwrites that week's drafts rather than producing next week's. Ordering matters.

### The current drafts are for a partially-observed week

The forecast week is `2026-08-17`, which `docs/phase-3-baseline.md` §9 flags as the trailing partial week the dataset drops — `invoice_lines` already holds sales inside it. These reminders therefore describe a week that has already partly happened. That resolves on the next data reload; until then, read the current batch with it in mind.

---

## 6. Soft Launch — 2026-08-20

First real use. The owner reviewed the drafts on `/reminders`, picked the stores he wanted, texted them from his own phone, and recorded the statuses.

### What the table shows

| | |
|---|---|
| Reminders drafted | 63 |
| Approved and sent | **6** |
| Still `draft` | 57 |
| Share of forecast units covered by the 6 | **50.0%** (7,269 of 14,541) |

| Store | Route | Forecast units | `approved_at` |
|---|---|---|---|
| WALMART SUP | 38265 | 1,638.7 | 17:07:36 |
| FOOD LION | 1483 | 1,629.9 | 17:07:44 |
| FOOD LION | 38265 | 1,546.8 | 17:07:47 |
| FOOD LION | 2140 | 1,345.9 | 17:07:50 |
| WALMART SUP | 2140 | 1,036.9 | 17:07:55 |
| FAMILY DOL | 38260 | 70.9 | 16:57:37 |

> ⚠️ **The owner recalls sending 5; the table records 6.** The top five were approved in one 20-second burst (17:07:36 → 17:07:55) and are exactly the five largest stores by forecast. The `FAMILY DOL` row sits ten minutes earlier at 16:57:37 and is two orders of magnitude smaller — it looks like a first click to see what the button did, not a sixth deliberate send. **Confirm which it was before treating these counts as a baseline**, since §4 makes them the measure of the whole phase. If it was a trial, reset that row to `draft`.

### What it tells us

- **Approve → sent in one sitting.** All six carry an `approved_at` and all six are at `sent`; none stopped at `approved`. The workflow is a single pass, not two — the two-step lifecycle is recording state, not pacing work.
- **He worked strictly top-down by forecast.** The five deliberate sends are the top five stores by predicted units, in order. That is how `/reminders` sorts, so the sort matches how the tool is actually used; do not change it without cause.
- **6 of 63 reminders covered half the forecast volume.** A small number of high-volume stores carries most of the book, which is worth knowing before optimizing draft quality across the long tail.
- **The near-duplicate problem hit on day one.** Four of the five deliberate sends were same-chain: three Food Lions and two Walmarts, all receiving near-identical messages (§5). This is no longer a theoretical risk — it happened in the first real use, to the highest-value stores on the route.

### Owner feedback

**Would use it weekly.** The drafts were good enough to send with no rewriting.

**The gap was not the drafts — it was not knowing the routine.** The tool did not say when to use it or in what order. Now defined:

> **Monday:** open `/reminders` → review the fresh drafts → approve the ones to send → copy → text the store → mark sent.

### Known operational gap — flagged for Phase 5

**The Monday routine above silently assumes fresh drafts, and nothing produces them.** Both steps are manual and order-dependent:

```
python scripts/forecast_model.py --write      # publish next week's forecast
python scripts/generate_reminders.py          # draft reminders from it
```

If neither is run, `/reminders` still renders — showing **last week's drafts, with no indication they are stale**. The page displays the week it is showing, but nothing flags that the week is old, and a Monday routine built on "open the page and review" will walk straight into it. Re-running only `generate_reminders.py` redrafts the same week rather than advancing, because the upsert key includes `week_start`.

This is the handoff problem for Phase 5: either automate both steps on a schedule, or make `/reminders` refuse to present drafts whose week has passed.

---

## 7. Where to Go Next

Read §4's ratios first — they should decide whether any of this is worth building. After the soft launch (§6) the standing count is 6 sent of 63 drafted, pending the 5-vs-6 confirmation.

Ordered by what the first real use actually surfaced:

- **Close the staleness gap (Phase 5).** The Monday routine assumes fresh drafts and nothing produces them. Automate `--write` → `generate_reminders.py` on a schedule, or make `/reminders` refuse to present drafts for a week that has passed. Everything else on this list is cosmetic next to a routine that quietly re-serves last week's messages.
- **Vary the drafts for same-chain stores.** No longer theoretical — four of five soft-launch sends were near-identical messages to three Food Lions and two Walmarts, the highest-value stores on the route. Pass the model the other drafts for that chain, or give it store-specific context it does not currently get (last order date, how long they have been a customer).
- **Add a display-name column to `stores`** to fix the truncated names at the source, before another "Hey Family Dol!" goes out.
- **Add a `sent_at` column** so time-to-send is measurable, not just final state.
- **Only then consider automating the send** — and only if draft→approved is high enough to justify it.
