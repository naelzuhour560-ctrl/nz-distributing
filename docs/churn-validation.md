# Churn Flag Validation — Call Sheet

The churn model has never been checked against reality. This is the sheet for doing that.

## Protocol

1. The owner contacts or otherwise confirms the current status of each store below.
2. Record the outcome in the **Outcome** column, and whether the flag was right in **Flag correct?**.
3. We compute **precision = correct flags / total flags** — of the stores we called churned, how many actually were.

A flag counts as **correct** if the store has genuinely stopped buying: closed, switched supplier, or otherwise gone. It counts as **incorrect** if the store is still an active customer — including seasonal accounts that are simply between seasons, since the model presented them as at-risk rather than dormant-by-nature.

### What this measures, and what it does not

- **Precision only.** This sheet contains only stores the model flagged, so it cannot tell us about churned stores the model *missed* (recall). A model that flags almost nothing scores high precision while being useless. Fixing that needs a second exercise over stores the model called healthy.
- **Eight flags is a coarse instrument.** Each store moves the precision figure by 12.5 points. Treat the result as a direction, not a measurement — "most of these were real" or "most of these were wrong", not a number to quote to two decimals.
- Record **seasonal** as its own outcome rather than folding it into correct/incorrect. If several land there, the fix is a cadence model that understands seasonality, not a different threshold.

## Flagged stores — `churn_ratio ≥ 2.6`

Source: `churn_overview()`, August 2026 data. **Days silent is measured to 2026-08-17**, the dataset's last date — not to today. `churn_ratio` = days since last sale ÷ that store's normal days between orders, so 27.7 means the store has been quiet 27.7× longer than its own usual gap.

| # | Store | Route | Last sale | Days silent | Historical revenue | Ratio | Outcome (closed / switched supplier / seasonal / still buys / other) | Flag correct? (Y/N) |
|---|---|---|---|---|---|---|---|---|
| 1 | CASH SALES | 1483 | 2025-10-27 | 294 | $225.84 | 58.8 | | |
| 2 | WHITS MARKET 2 Weeks | 38265 | 2025-03-04 | 531 | $287.10 | 32.5 | | |
| 3 | ROYAL | 38265 | 2025-07-21 | 392 | $676.20 | 27.7 | | |
| 4 | NEW MRKT SUBWAY EXXO | 1483 | 2025-02-18 | 545 | $105.48 | 26.0 | | |
| 5 | C&m Market Deli Exsp | 38260 | 2026-02-16 | 182 | $2,182.11 | 22.8 | | |
| 6 | EZ FOODMART | 2140 | 2025-12-23 | 237 | $1,824.90 | 17.7 | | |
| 7 | J N' R MART | 1483 | 2025-09-19 | 332 | $550.44 | 8.9 | | |
| 8 | CIRCLE K 33 | 38265 | 2026-07-19 | 29 | $3,642.81 | 2.6 | | |

**Precision: ____ / 8 = ____%**

## Before making the calls

Three of these rows deserve a look before the phone comes out — they may say more about the data than about the customers.

- **Row 1, CASH SALES, is probably not a store.** The name reads as a counter-sales or cash-transaction bucket rather than a customer, and at $225.84 lifetime it is the second-smallest account here. If it is a bookkeeping category, it should be excluded from churn scoring entirely rather than marked as a wrong flag — that is a data fix, not a model error.
- **Row 2, WHITS MARKET 2 Weeks, has a delivery cadence baked into its name.** That suggests store names in this data carry operational annotations, which affects how reliably a "store" is a store. Worth confirming whether this is one account or an artefact of how the name was entered.
- **Row 8, CIRCLE K 33, is the weakest flag and the most expensive to get wrong.** It sits exactly on the threshold, has been quiet only 29 days against an 11.2-day cadence, and is the **largest account on the sheet at $3,642.81** — 1.7× the next largest. The `/churn` page currently displays it as **Active** (green), because that page's own cutoff for "At risk" is ratio > 3. So this sheet flags a store the dashboard tells you is fine. Whichever way the call goes, the two thresholds should be reconciled.

Note also that the eight span a 35× revenue range, from $105 to $3,643, and the sheet is ordered by ratio rather than by money. If time is short, work rows 8, 5 and 6 first — they carry $7,650 of the $9,495 total historical revenue between them.

## After the calls

Record the result here, then decide the threshold from evidence rather than from the shape of the distribution:

- If precision is high and the misses are all seasonal, the model is working and needs a seasonality exception.
- If the low-ratio flags (rows 7–8) are the wrong ones, raise the threshold; the high-ratio end is doing real work.
- If flags fail across the whole range, the cadence-relative approach itself is suspect, not its cutoff.
