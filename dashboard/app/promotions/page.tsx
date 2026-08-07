import { supabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

interface PromoRow {
  upc: string;
  product_name: string;
  sale_units: number;
  sale_dollars: number;
  promo_dollars: number;
  promo_pct_of_sales: number;
  promo_per_unit: number;
}

function fmt(n: number) {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default async function PromotionsPage() {
  const { data } = await supabase.rpc("promo_spend");
  const rows = ((data ?? []) as PromoRow[]).slice(0, 40);

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Promotion Spend</h2>
      <p className="text-sm text-zinc-500 mb-6">
        Promotion allowance given per product, ranked by total promo dollars.
        &ldquo;Promo % of Sales&rdquo; shows how heavily each product is
        discounted — the core snack cakes sit around 6%, so products well above
        that (e.g. granola bars near 12%) are discounted unusually heavily. This
        is descriptive spend analysis, not ROI: the data cannot measure sales
        that a promotion caused versus sales that would have happened anyway.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-700 text-zinc-400">
              <th className="py-2 text-left font-medium">Product</th>
              <th className="py-2 text-right font-medium">UPC</th>
              <th className="py-2 text-right font-medium">Sale Units</th>
              <th className="py-2 text-right font-medium">Sale $</th>
              <th className="py-2 text-right font-medium">Promo $</th>
              <th className="py-2 text-right font-medium">Promo % of Sales</th>
              <th className="py-2 text-right font-medium">Promo per Unit</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.upc} className="border-b border-zinc-800">
                <td className="py-2 font-mono">{r.product_name}</td>
                <td className="py-2 text-right font-mono">{r.upc}</td>
                <td className="py-2 text-right font-mono">
                  {r.sale_units.toLocaleString()}
                </td>
                <td className="py-2 text-right font-mono">{fmt(r.sale_dollars)}</td>
                <td className="py-2 text-right font-mono">{fmt(r.promo_dollars)}</td>
                <td className="py-2 text-right font-mono">
                  {r.promo_pct_of_sales.toFixed(1)}%
                </td>
                <td className="py-2 text-right font-mono">
                  ${r.promo_per_unit.toFixed(3)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
