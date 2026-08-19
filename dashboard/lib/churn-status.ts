/**
 * Churn status, shared by /churn and the Store 360 page.
 *
 * Two signals, in order of authority:
 *
 *  1. The owner's cut-off. He treats a store with no sale for roughly 60 days
 *     as churned and cuts it off; he does not pursue win-backs. This is a
 *     business rule, not an inference, so it decides the answer whenever it
 *     applies — including for stores with too little history to have a cadence.
 *  2. Cadence ratio. Within the 60-day window, how long a store has been quiet
 *     relative to its own normal gap between orders. A fortnightly account
 *     silent for six weeks is a different signal from a daily one silent for
 *     six weeks, and the ratio is what separates them.
 *
 * Validated against the owner in docs/churn-validation.md: all seven flags at
 * 180+ days silent were confirmed churned, and the one flag inside the window
 * (CIRCLE K 33, 29 days) was confirmed still active.
 */

export const CADENCE_RATIO_ACTIVE = 3;
export const CADENCE_RATIO_CHURNED = 10;
export const OWNER_CUTOFF_DAYS = 60;

/** A near-daily orderer's ratio is too twitchy to read; use absolute days. */
const NEAR_DAILY_CADENCE = 2;
const NEAR_DAILY_ACTIVE_DAYS = 30;

export interface ChurnInput {
  avg_days_between_orders: number | null;
  days_since_last_sale: number;
  churn_ratio?: number | null;
}

export interface ChurnStatus {
  label: string;
  color: string;
}

const ACTIVE: ChurnStatus = { label: "Active", color: "text-green-400" };
const AT_RISK: ChurnStatus = { label: "At risk", color: "text-amber-400" };
const CHURNED: ChurnStatus = { label: "Likely churned", color: "text-red-400" };
const UNKNOWN: ChurnStatus = {
  label: "Insufficient history",
  color: "text-zinc-500",
};

export function churnStatus(r: ChurnInput | null): ChurnStatus {
  if (!r) return UNKNOWN;

  // The owner's cut-off runs first and overrides everything below it. It is
  // also the only rule that works without cadence history, so a long-silent
  // store no longer hides behind "Insufficient history".
  if (r.days_since_last_sale > OWNER_CUTOFF_DAYS) return CHURNED;

  if (r.avg_days_between_orders == null) return UNKNOWN;

  if (r.avg_days_between_orders < NEAR_DAILY_CADENCE) {
    return r.days_since_last_sale <= NEAR_DAILY_ACTIVE_DAYS ? ACTIVE : AT_RISK;
  }

  const ratio =
    r.churn_ratio ?? r.days_since_last_sale / r.avg_days_between_orders;

  if (ratio <= CADENCE_RATIO_ACTIVE) return ACTIVE;
  if (ratio <= CADENCE_RATIO_CHURNED) return AT_RISK;
  return CHURNED;
}
