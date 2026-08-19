import { supabase } from "@/lib/supabase";
import { getDataRange } from "@/lib/data-range";

export const dynamic = "force-dynamic";

interface ProductRow {
  upc: string;
  product_name: string;
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

export default async function ProductsPage() {
  const [{ data }, range] = await Promise.all([
    supabase.rpc("top_products").limit(25),
    getDataRange(),
  ]);
  const rows = (data ?? []) as ProductRow[];

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Top Products by Net Revenue</h2>
      <p className="text-sm text-zinc-500 mb-6">
        Ranked across all routes. Figures cover {range.label}.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-700 text-zinc-400">
              <th className="py-2 text-left font-medium">Product</th>
              <th className="py-2 text-right font-medium">UPC</th>
              <th className="py-2 text-right font-medium">Sales $</th>
              <th className="py-2 text-right font-medium">Returns $</th>
              <th className="py-2 text-right font-medium">Buybacks $</th>
              <th className="py-2 text-right font-medium">Net $</th>
              <th className="py-2 text-right font-medium">Sale Units</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.upc} className="border-b border-zinc-800">
                <td className="py-2 font-mono">{r.product_name}</td>
                <td className="py-2 text-right font-mono">{r.upc}</td>
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
