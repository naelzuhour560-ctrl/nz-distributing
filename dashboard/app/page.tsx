import { supabase } from "@/lib/supabase";
import RevenueChart from "./revenue-chart";

export const dynamic = "force-dynamic";

interface TotalsRow {
  row_count: number;
  total_units: number;
  total_wholesale_dollars: number;
}

interface MonthlyRow {
  month: string;
  net_dollars: number;
  sale_dollars: number;
}

export default async function Page() {
  const [{ data: totals }, { data: monthly }] = await Promise.all([
    supabase.rpc("invoice_lines_totals").single(),
    supabase.rpc("monthly_revenue"),
  ]);

  const t = totals as TotalsRow | null;
  const rowCount = t?.row_count ?? null;
  const totalUnits = t?.total_units ?? null;
  const totalDollars = t?.total_wholesale_dollars ?? null;

  const monthlyRows = (monthly ?? []) as MonthlyRow[];

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
