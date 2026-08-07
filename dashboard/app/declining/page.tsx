import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

interface DecliningRow {
  upc: string;
  product_name: string;
  total_units: number;
  total_dollars: number;
  last_90_units: number;
  prior_units: number;
  last_sale_date: string;
  pct_decline: number;
}

function fmt(n: number) {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default async function DecliningPage() {
  const { data } = await supabase.rpc("dead_stock");
  const rows = ((data ?? []) as DecliningRow[]).slice(0, 40);

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Declining Products</h2>
      <p className="text-sm text-zinc-500 mb-6">
        Products with the steepest drop in unit sales between the prior 90-day
        window and the most recent 90 days of data. NOTE: seasonal items
        (Christmas, Valentine&apos;s, etc.) appear here when their season ends —
        check the Last Sale date to distinguish normal seasonal winddown from a
        year-round product that has genuinely stopped selling.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-700 text-zinc-400">
              <th className="py-2 text-left font-medium">Product</th>
              <th className="py-2 text-right font-medium">UPC</th>
              <th className="py-2 text-right font-medium">Last Sale</th>
              <th className="py-2 text-right font-medium">Units (prior 90d)</th>
              <th className="py-2 text-right font-medium">Units (last 90d)</th>
              <th className="py-2 text-right font-medium">Decline %</th>
              <th className="py-2 text-right font-medium">Lifetime $</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.upc} className="border-b border-zinc-800">
                <td className="py-2 font-mono">{r.product_name}</td>
                <td className="py-2 text-right font-mono">{r.upc}</td>
                <td className="py-2 text-right font-mono">{r.last_sale_date}</td>
                <td className="py-2 text-right font-mono">
                  {r.prior_units.toLocaleString()}
                </td>
                <td className="py-2 text-right font-mono">
                  {r.last_90_units.toLocaleString()}
                </td>
                <td className="py-2 text-right font-mono text-red-400">
                  {r.pct_decline.toFixed(1)}%
                </td>
                <td className="py-2 text-right font-mono">{fmt(r.total_dollars)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
