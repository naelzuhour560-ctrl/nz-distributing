import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { getDataRange } from "@/lib/data-range";
import { churnStatus, OWNER_CUTOFF_DAYS } from "@/lib/churn-status";

export const dynamic = "force-dynamic";

interface ChurnRow {
  location_id: number;
  store_name: string;
  last_sale_date: string;
  avg_days_between_orders: number | null;
  days_since_last_sale: number;
  sale_revenue: number;
  churn_ratio: number | null;
}

function fmt(n: number) {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default async function ChurnPage() {
  const [{ data }, range] = await Promise.all([
    supabase.rpc("churn_overview"),
    getDataRange(),
  ]);
  const rows = (data ?? []) as ChurnRow[];

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Churn Overview</h2>
      <p className="text-sm text-zinc-500 mb-6">
        All stores ranked by churn risk (days since last sale relative to normal
        order cadence). Measured to the dataset&apos;s last date, {range.lastDate}.
      </p>
      <p className="text-sm text-zinc-500 mb-6 max-w-3xl">
        A store counts as churned once it has been silent for more than{" "}
        {OWNER_CUTOFF_DAYS} days — the cut-off the owner actually works to —
        or once it has been quiet more than 3× its own normal gap between
        orders, whichever comes first.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-700 text-zinc-400">
              <th className="py-2 text-left font-medium">Store</th>
              <th className="py-2 text-right font-medium">Route</th>
              <th className="py-2 text-right font-medium">Last Sale</th>
              <th className="py-2 text-right font-medium">Avg Days Between Orders</th>
              <th className="py-2 text-right font-medium">Days Since Last Sale</th>
              <th className="py-2 text-right font-medium">Revenue $</th>
              <th className="py-2 text-left font-medium pl-4">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const status = churnStatus(r);
              return (
                <tr
                  key={`${r.store_name}-${r.location_id}`}
                  className="border-b border-zinc-800"
                >
                  <td className="py-2 font-mono">
                    <Link
                      href={`/stores/${r.location_id}/${encodeURIComponent(r.store_name)}`}
                      className="text-blue-400 hover:text-blue-300 underline underline-offset-2"
                    >
                      {r.store_name}
                    </Link>
                  </td>
                  <td className="py-2 text-right font-mono">{r.location_id}</td>
                  <td className="py-2 text-right font-mono">
                    {r.last_sale_date}
                  </td>
                  <td className="py-2 text-right font-mono">
                    {r.avg_days_between_orders != null
                      ? r.avg_days_between_orders.toFixed(1)
                      : "—"}
                  </td>
                  <td className="py-2 text-right font-mono">
                    {r.days_since_last_sale}
                  </td>
                  <td className="py-2 text-right font-mono">
                    {fmt(r.sale_revenue)}
                  </td>
                  <td className="py-2 pl-4">
                    <span className={`font-semibold ${status.color}`}>
                      {status.label}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
