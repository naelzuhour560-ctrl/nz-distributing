import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export default async function Page() {
  const { data } = await supabase.rpc("invoice_lines_totals").single();

  const rowCount = data?.row_count as number | null;
  const totalUnits = data?.total_units as number | null;
  const totalDollars = data?.total_wholesale_dollars as number | null;

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
    </div>
  );
}
