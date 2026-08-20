#!/usr/bin/env python3
"""
scripts/generate_reminders.py
-----------------------------
Draft a reorder reminder for each store with a meaningful forecast next week,
using the Claude API, and save the drafts to the reminders table.

Reads .env for SUPABASE_URL, SUPABASE_SECRET_KEY, and ANTHROPIC_API_KEY.

Everything written here is a DRAFT (status 'draft'). Nothing is sent to a
store; approving and sending is a separate, human step.

Flow:
  1. Read next week's forecasts via forecast_next_week() (paginated).
  2. Group by store; keep stores forecast at >= MIN_STORE_UNITS units;
     take each store's top TOP_PRODUCTS products by predicted units.
  3. Ask Claude for a short, friendly SMS-length reminder per store.
  4. Upsert into reminders on (location_id, store_name, week_start).
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]

# PostgREST caps a response at 1,000 rows however wide the requested range is,
# so a single .rpc() call returns the first page rather than the whole forecast.
PAGE_SIZE = 1000

MIN_STORE_UNITS = 10
TOP_PRODUCTS = 5
MAX_CHARS = 400

UPSERT_KEY = "location_id,store_name,week_start"

# Sonnet 4.6 with thinking off and low effort: this is short-form content
# generation, not reasoning, and the pair is the documented setting for it.
# max_tokens is deliberately small — the deliverable is under 400 characters,
# so a large budget would only mask a runaway response.
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 512

SYSTEM_PROMPT = """You write short reorder reminders for N&Z Distributing, a \
Little Debbie snack distributor, to send to the convenience stores and \
supermarkets on their delivery routes.

Write one message per request, following all of these rules:

- Greet the store by name.
- Mention 2-3 of the products they usually order, by name.
- Ask whether they would like their regular delivery this week.
- Keep it warm and casual, like a rep who knows them — not a marketing blast.
- Under 400 characters. Shorter is better; this is sent as an SMS.
- Never mention prices, discounts, totals, or unit counts.
- Never push, upsell, or create urgency. No "act now", no "don't miss out".
- Sign off as N&Z Distributing.

Reply with the message text only — no preamble, no quotation marks, no notes."""


def fetch_all_forecasts(sb, verbose=True):
    """Every row of forecast_next_week(), paged past the PostgREST cap."""
    rows = []
    offset = 0
    while True:
        r = sb.rpc("forecast_next_week").range(offset, offset + PAGE_SIZE - 1).execute()
        if not r.data:
            break
        rows.extend(r.data)
        offset += len(r.data)

    if verbose:
        print(f"  forecast rows: {len(rows):,}")
    return rows


def group_by_store(rows):
    """
    Collapse forecast rows into one entry per store, keeping only stores worth
    contacting and each store's biggest products.

    A store forecast under MIN_STORE_UNITS units is not worth a message — the
    reminder would cost more attention than the order is worth.
    """
    by_store = defaultdict(list)
    for r in rows:
        by_store[(r["location_id"], r["store_name"], r["week_start"])].append(r)

    stores = []
    for (location_id, store_name, week_start), items in by_store.items():
        total = sum(i["predicted_units"] for i in items)
        if total < MIN_STORE_UNITS:
            continue

        items.sort(key=lambda i: -i["predicted_units"])
        stores.append({
            "location_id": location_id,
            "store_name": store_name,
            "week_start": week_start,
            "predicted_total_units": round(total, 3),
            "top_products": [
                {
                    "upc": i["upc"],
                    "product_name": i["product_name"],
                    "predicted_units": round(i["predicted_units"], 3),
                }
                for i in items[:TOP_PRODUCTS]
            ],
        })

    stores.sort(key=lambda s: -s["predicted_total_units"])
    return stores


def draft_message(client, store):
    """
    Ask Claude for one store's reminder.

    Returns (text, retried). Over-length drafts get one corrective retry —
    MAX_CHARS is an SMS constraint, so a long draft is unusable rather than
    merely untidy.
    """
    product_list = "\n".join(
        f"- {p['product_name']}" for p in store["top_products"]
    )
    user_prompt = (
        f"Store name: {store['store_name']}\n"
        f"Products they usually order, most frequent first:\n{product_list}"
    )

    messages = [{"role": "user", "content": user_prompt}]

    for attempt in range(2):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            thinking={"type": "disabled"},
            output_config={"effort": "low"},
            messages=messages,
        )

        if response.stop_reason == "refusal":
            raise RuntimeError("model declined to draft this message")

        text = "".join(
            b.text for b in response.content if b.type == "text"
        ).strip()

        if len(text) <= MAX_CHARS:
            return text, attempt > 0

        # Too long — show it its own draft and ask again. Only once; if the
        # second attempt is still over, keep it and report rather than looping.
        messages = messages + [
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": (
                    f"That draft is {len(text)} characters. Rewrite it under "
                    f"{MAX_CHARS} characters, keeping the same warmth and the "
                    f"product mentions."
                ),
            },
        ]

    return text, True


def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⛔  ANTHROPIC_API_KEY is not set (checked the environment and .env).")
        print("    Add it to .env and re-run:")
        print("      echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env")
        sys.exit(1)

    # Retries above the default 2: this makes one API call per store, and a
    # single 429 partway through should not cost the whole run.
    client = anthropic.Anthropic(max_retries=4)

    print("── Generate Reminders ───────────────────────────────────────────────\n")

    rows = fetch_all_forecasts(sb)
    if not rows:
        print("⛔  forecast_next_week() returned nothing — run "
              "forecast_model.py --write first.")
        sys.exit(1)

    stores = group_by_store(rows)
    week_start = rows[0]["week_start"]
    skipped = len({(r["location_id"], r["store_name"]) for r in rows}) - len(stores)

    print(f"  week starting:   {week_start}")
    print(f"  stores to draft: {len(stores)}  "
          f"(skipped {skipped} under {MIN_STORE_UNITS} units)")
    print(f"  model:           {MODEL}\n")

    generated_at = datetime.now(timezone.utc).isoformat()
    written = 0
    retried = 0
    failures = []

    for i, store in enumerate(stores, 1):
        label = f"[{i}/{len(stores)}] {store['store_name']} (route {store['location_id']})"
        try:
            text, was_retried = draft_message(client, store)
        except anthropic.RateLimitError as e:
            failures.append((store["store_name"], f"rate limited: {e}"))
            print(f"  {label}: FAILED — rate limited", flush=True)
            continue
        except anthropic.APIStatusError as e:
            failures.append((store["store_name"], f"HTTP {e.status_code}: {e.message}"))
            print(f"  {label}: FAILED — HTTP {e.status_code}", flush=True)
            continue
        except anthropic.APIConnectionError as e:
            failures.append((store["store_name"], f"connection error: {e}"))
            print(f"  {label}: FAILED — connection error", flush=True)
            continue
        except RuntimeError as e:
            failures.append((store["store_name"], str(e)))
            print(f"  {label}: FAILED — {e}", flush=True)
            continue

        retried += was_retried

        # Upserted per store rather than batched at the end: each row cost an
        # API call, so a crash partway through should not discard the drafts
        # already paid for.
        sb.table("reminders").upsert(
            {
                "location_id": store["location_id"],
                "store_name": store["store_name"],
                "week_start": store["week_start"],
                "draft_message": text,
                "top_products": store["top_products"],
                "predicted_total_units": store["predicted_total_units"],
                "status": "draft",
                "generated_at": generated_at,
            },
            on_conflict=UPSERT_KEY,
        ).execute()
        written += 1

        flag = "  (retried for length)" if was_retried else ""
        print(f"  {label}: {len(text)} chars{flag}", flush=True)

    # ── Verify ────────────────────────────────────────────────────────────

    check = (
        sb.table("reminders")
        .select("id", count="exact")
        .eq("week_start", week_start)
        .eq("status", "draft")
        .execute()
    )

    print(f"\n── Summary ──────────────────────────────────────────────────────────\n")
    print(f"  drafts written:      {written}")
    print(f"  retried for length:  {retried}")
    print(f"  failed:              {len(failures)}")
    for name, reason in failures:
        print(f"    - {name}: {reason}")
    print(f"\n  reminders rows @ {week_start} (status=draft): {check.count}")

    if check.count != written:
        print(f"\n⚠️  Wrote {written} but the table reports {check.count} — an "
              f"earlier run may have left rows for this week.")
    else:
        print(f"\n✅  {written} drafts saved. All status 'draft' — nothing sent.")


if __name__ == "__main__":
    main()
