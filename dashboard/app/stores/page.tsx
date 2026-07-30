import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

interface StoreRow {
  store_name: string;
  location_id: number;
  sale_dollars: number;
  return_dollars: number;
  buyback_dollars: number;
  net_dollars: number;
  sale_units: number;
}

function fmt(n: number) {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default async function StoresPage() {
  const { data } = await supabase.rpc("top_stores").limit(25);
  const rows = (data ?? []) as StoreRow[];

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Top Stores by Net Revenue</h2>
      <p className="text-sm text-zinc-500 mb-6">
        Grouped by store name per route. Chain names (e.g. Food Lion) appear
        once per route; individual locations within the same route can&apos;t be
        separated from invoice data. Figures cover Jan 2025 – Jun 2026.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-700 text-zinc-400">
              <th className="py-2 text-left font-medium">Store</th>
              <th className="py-2 text-right font-medium">Route</th>
              <th className="py-2 text-right font-medium">Sales $</th>
              <th className="py-2 text-right font-medium">Returns $</th>
              <th className="py-2 text-right font-medium">Buybacks $</th>
              <th className="py-2 text-right font-medium">Net $</th>
              <th className="py-2 text-right font-medium">Sale Units</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.store_name}-${r.location_id}`} className="border-b border-zinc-800">
                <td className="py-2 font-mono">{r.store_name}</td>
                <td className="py-2 text-right font-mono">{r.location_id}</td>
                <td className="py-2 text-right font-mono">{fmt(r.sale_dollars)}</td>
                <td className="py-2 text-right font-mono">{fmt(r.return_dollars)}</td>
                <td className="py-2 text-right font-mono">{fmt(r.buyback_dollars)}</td>
                <td className="py-2 text-right font-mono font-semibold">
                  {fmt(r.net_dollars)}
                </td>
                <td className="py-2 text-right font-mono">
                  {r.sale_units.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
