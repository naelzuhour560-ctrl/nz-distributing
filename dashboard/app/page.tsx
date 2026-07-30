import { supabase } from "@/lib/supabase";
import RevenueChart from "./revenue-chart";

export const dynamic = "force-dynamic";

export default async function Page() {
  const [{ data: totals }, { data: monthly }] = await Promise.all([
    supabase.rpc("invoice_lines_totals").single(),
    supabase.rpc("monthly_revenue"),
  ]);

  const rowCount = totals?.row_count as number | null;
  const totalUnits = totals?.total_units as number | null;
  const totalDollars = totals?.total_wholesale_dollars as number | null;

  const monthlyRows = (monthly ?? []) as {
    month: string;
    net_dollars: number;
    sale_dollars: number;
  }[];

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Overview</h2>
      <dl className="space-y-2">
        <div>
          <dt className="text-sm text-zinc-500">Invoice rows</dt>
          <dd className="text-xl font-mono">
            {rowCount?.toLocaleString() ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-sm text-zinc-500">Total units</dt>
          <dd className="text-xl font-mono">
            {totalUnits?.toLocaleString() ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-sm text-zinc-500">Total wholesale dollars</dt>
          <dd className="text-xl font-mono">
            {totalDollars != null
              ? `$${totalDollars.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`
              : "—"}
          </dd>
        </div>
      </dl>

      <h3 className="text-xl font-bold mt-10 mb-4">Monthly Revenue Trend</h3>
      <RevenueChart data={monthlyRows} />
    </div>
  );
}
