import { supabase } from "@/lib/supabase";
import { getDataRange } from "@/lib/data-range";

export const dynamic = "force-dynamic";

interface RouteRow {
  location_id: number;
  route_name: string;
  transaction_type: "Sale" | "Return" | "Buyback";
  line_count: number;
  total_units: number;
  total_wholesale_dollars: number;
}

function fmt(n: number) {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default async function RoutesPage() {
  const [{ data }, range] = await Promise.all([
    supabase.rpc("revenue_by_route"),
    getDataRange(),
  ]);
  const rows = (data ?? []) as RouteRow[];

  // Pivot: one entry per route
  const byRoute = new Map<
    string,
    { sale: number; return_: number; buyback: number; saleUnits: number }
  >();

  for (const r of rows) {
    if (!byRoute.has(r.route_name)) {
      byRoute.set(r.route_name, { sale: 0, return_: 0, buyback: 0, saleUnits: 0 });
    }
    const entry = byRoute.get(r.route_name)!;
    if (r.transaction_type === "Sale") {
      entry.sale += r.total_wholesale_dollars;
      entry.saleUnits += r.total_units;
    } else if (r.transaction_type === "Return") {
      entry.return_ += r.total_wholesale_dollars;
    } else if (r.transaction_type === "Buyback") {
      entry.buyback += r.total_wholesale_dollars;
    }
  }

  const routes = Array.from(byRoute.entries()).map(([name, v]) => ({
    name,
    sale: v.sale,
    return_: v.return_,
    buyback: v.buyback,
    net: v.sale + v.return_ + v.buyback,
    saleUnits: v.saleUnits,
  }));

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Revenue by Route</h2>
      <p className="text-sm text-zinc-500 mb-6">
        Figures cover the full loaded period ({range.label})
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-700 text-zinc-400">
              <th className="py-2 text-left font-medium">Route</th>
              <th className="py-2 text-right font-medium">Sales $</th>
              <th className="py-2 text-right font-medium">Returns $</th>
              <th className="py-2 text-right font-medium">Buybacks $</th>
              <th className="py-2 text-right font-medium">Net $</th>
              <th className="py-2 text-right font-medium">Sale Units</th>
            </tr>
          </thead>
          <tbody>
            {routes.map((r) => (
              <tr key={r.name} className="border-b border-zinc-800">
                <td className="py-2 font-mono">{r.name}</td>
                <td className="py-2 text-right font-mono">{fmt(r.sale)}</td>
                <td className="py-2 text-right font-mono">{fmt(r.return_)}</td>
                <td className="py-2 text-right font-mono">{fmt(r.buyback)}</td>
                <td className="py-2 text-right font-mono font-semibold">
                  {fmt(r.net)}
                </td>
                <td className="py-2 text-right font-mono">
                  {r.saleUnits.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
