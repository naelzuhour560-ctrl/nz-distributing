# Churn Flag Validation — Result

**Status: complete.** The owner reviewed the flagged stores. Precision **7 / 8 = 87.5%**, and the exercise produced something more useful than the score — an explicit decision rule, which is now what the dashboard implements.

## The owner's decision rule

> **A store with no sale for roughly 60 days is churned. It gets cut off. He does not pursue win-backs.**

This is a business rule, not an estimate, and it settles several things the model had been guessing at:

- There is no meaningful "at risk" window to act inside. By the time a store crosses 60 days it is already gone, by decision rather than by inference.
- **Why** a store stopped buying does not change what happens to it. Closed, switched supplier, or seasonal all lead to the same action.
- The cut-off is absolute, not cadence-relative. A fortnightly account and a daily account are both cut at the same 60 days.

## Outcome

Source: `churn_overview()`, August 2026 data, `churn_ratio ≥ 2.6`. Days silent measured to 2026-08-17, the dataset's last date.

| # | Store | Route | Last sale | Days silent | Historical revenue | Ratio | Outcome | Flag correct? |
|---|---|---|---|---|---|---|---|---|
| 1 | CASH SALES | 1483 | 2025-10-27 | 294 | $225.84 | 58.8 | Churned — past cut-off | Y |
| 2 | WHITS MARKET 2 Weeks | 38265 | 2025-03-04 | 531 | $287.10 | 32.5 | Churned — past cut-off | Y |
| 3 | ROYAL | 38265 | 2025-07-21 | 392 | $676.20 | 27.7 | Churned — past cut-off | Y |
| 4 | NEW MRKT SUBWAY EXXO | 1483 | 2025-02-18 | 545 | $105.48 | 26.0 | Churned — past cut-off | Y |
| 5 | C&m Market Deli Exsp | 38260 | 2026-02-16 | 182 | $2,182.11 | 22.8 | Churned — past cut-off | Y |
| 6 | EZ FOODMART | 2140 | 2025-12-23 | 237 | $1,824.90 | 17.7 | Churned — past cut-off | Y |
| 7 | J N' R MART | 1483 | 2025-09-19 | 332 | $550.44 | 8.9 | Churned — past cut-off | Y |
| 8 | CIRCLE K 33 | 38265 | 2026-07-19 | 29 | $3,642.81 | 2.6 | Still buying — inside cut-off | **N** |

**Precision: 7 / 8 = 87.5%**

Rows 1–7 are all 180+ days silent and sit far past the cut-off; none was a marginal call. Row 8 was silent 29 days, less than half the cut-off, and is a live account.

### Per-store outcomes were not collected

The sheet asked for closed / switched supplier / seasonal / still buys. Only the last is recorded. The owner treats the first three identically — the store is cut off either way — so the distinction had no operational meaning to him and was not worth his time to reconstruct. That does mean **we cannot separate seasonal dormancy from genuine loss**, so if a seasonal-aware model is ever wanted, the data for it does not exist yet.

### The threshold disagreement is resolved

The call sheet flagged CIRCLE K 33 at `churn_ratio` 2.6 while the `/churn` page displayed it as **Active** (its cut-off being ratio > 3). The two disagreed about the largest account on the sheet. **The dashboard was right.** At 29 days silent against an 11.2-day cadence, the store is well inside the owner's window, and it is still buying. The 2.6 threshold used to build the sheet was too aggressive; it has not been adopted anywhere.

## What this changed in the product

`lib/churn-status.ts` now implements both signals, shared by `/churn` and Store 360 so the two pages cannot disagree about a store again:

```
churned  when days_since_last_sale > 60          (owner's rule — decides outright)
         or  churn_ratio > 10                    (cadence signal, within the window)
at risk  when churn_ratio > 3                    (cadence signal, within the window)
active   otherwise
```

The 60-day cut-off is evaluated first, because it is a decision rather than an inference and it needs no cadence history to apply.

Effect across all 77 stores: **4 change status, none of them CIRCLE K 33.**

| Store | Days silent | Was | Now |
|---|---|---|---|
| J N' R MART | 332 | At risk | Likely churned |
| FORESTVILLE MARKET | 137 | Insufficient history | Likely churned |
| ROADSIDE MARKET | 77 | Insufficient history | Likely churned |
| Exxon | 61 | Insufficient history | Likely churned |

**The three "Insufficient history" stores are the real gain here.** They had too few orders to compute a cadence, so the old logic rendered them grey and unactionable — silent for 61, 77 and 137 days while the dashboard declined to draw a conclusion. The owner's rule needs no cadence, so they are now correctly shown as churned. The `Insufficient history` bucket is now empty.

## Caveats

- **Precision cannot be re-measured this way again.** The model now implements the owner's rule, so testing the model against that rule is circular — it will score 100% by construction. This exercise was worth doing once, to *set* the rule; it cannot validate it.
- **Recall is still unmeasured.** The sheet contained only flagged stores, so nothing here says how many churned stores the model missed. That needs a separate pass over stores currently shown as Active.
- **The three newly-churned stores were never validated.** FORESTVILLE MARKET, ROADSIDE MARKET and Exxon have a null `churn_ratio`, so they never appeared on the call sheet. They are flagged now purely by the 60-day rule. Exxon at 61 days is one day past the line.
- **Row 8 was the expensive one, and it was the wrong flag.** The single incorrect flag was also the largest account on the sheet at $3,642.81 — 1.7× the next largest. A cut-off set from ratio alone would have cost the biggest live customer on the list.

## Open items

- **CASH SALES is probably not a store.** It reads as a counter-sales or cash-transaction bucket rather than a customer. The owner's blanket rule marks it churned, which is harmless, but it should be excluded from churn scoring at the data level rather than counted as a customer that was lost.
- **`WHITS MARKET 2 Weeks` carries a delivery cadence in its name**, suggesting store names in this data hold operational annotations. Worth confirming whether that is one account or an artefact of data entry.
