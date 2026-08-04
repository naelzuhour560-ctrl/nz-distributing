import Link from "next/link";
import { supabase } from "@/lib/supabase";
import RevenueChart from "@/app/revenue-chart";

export const dynamic = "force-dynamic";

interface MarginRow {
  margin_pct: number;
  gross_margin: number;
  sale_revenue: number;
}

interface ChurnRow {
  last_sale_date: string;
  avg_days_between_orders: number | null;
  days_since_last_sale: number;
}

interface MonthlyRow {
  month: string;
  net_dollars: number;
  sale_dollars: number;
}

interface BasketRow {
  upc: string;
  product_name: string;
  sale_dollars: number;
  net_dollars: number;
  sale_units: number;
}

function fmt(n: number) {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtPct(n: number) {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }) + "%";
}

export default async function StoreDetailPage({
  params,
}: {
  params: Promise<{ route: string; store: string }>;
}) {
  const { route, store } = await params;
  const locationId = parseInt(route, 10);
  const storeName = decodeURIComponent(store);

  const [
    { data: margin },
    { data: churn },
    { data: monthly },
    { data: basket },
  ] = await Promise.all([
    supabase
      .rpc("store_margin", { p_location_id: locationId, p_store_name: storeName })
      .single(),
    supabase
      .rpc("store_churn", { p_location_id: locationId, p_store_name: storeName })
      .single(),
    supabase.rpc("store_monthly", {
      p_location_id: locationId,
      p_store_name: storeName,
    }),
    supabase.rpc("store_basket", {
      p_location_id: locationId,
      p_store_name: storeName,
    }),
  ]);

  const m = margin as MarginRow | null;
  const c = churn as ChurnRow | null;
  const monthlyRows = (monthly ?? []) as MonthlyRow[];
  const basketRows = ((basket ?? []) as BasketRow[]).slice(0, 25);

  // Churn status
  let churnLabel = "Insufficient order history";
  let churnColor = "text-zinc-500";
  if (c?.avg_days_between_orders != null) {
    if (c.avg_days_between_orders < 2) {
      // Near-daily orderer — use absolute days since last sale
      if (c.days_since_last_sale <= 30) {
        churnLabel = "Active";
        churnColor = "text-green-400";
      } else if (c.days_since_last_sale <= 90) {
        churnLabel = "At risk";
        churnColor = "text-amber-400";
      } else {
        churnLabel = "Likely churned";
        churnColor = "text-red-400";
      }
    } else {
      const ratio = c.days_since_last_sale / c.avg_days_between_orders;
      if (ratio <= 3) {
        churnLabel = "Active";
        churnColor = "text-green-400";
      } else if (ratio <= 10) {
        churnLabel = "At risk";
        churnColor = "text-amber-400";
      } else {
        churnLabel = "Likely churned";
        churnColor = "text-red-400";
      }
    }
  }

  return (
    <div>
      {/* Back link + heading */}
      <Link
        href="/stores"
        className="text-sm text-blue-400 hover:text-blue-300 mb-4 inline-block"
      >
        ← Back to stores
      </Link>
      <h2 className="text-2xl font-bold mb-1">{storeName}</h2>
      <p className="text-sm text-zinc-500 mb-8">Route {locationId}</p>

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-10">
        <div className="rounded-lg border border-zinc-800 p-4">
          <dt className="text-sm text-zinc-500">Gross Margin</dt>
          <dd className="text-xl font-mono mt-1">
            {m ? fmtPct(m.margin_pct) : "—"}
          </dd>
          <p className="text-xs text-zinc-600 mt-1">
            Revenue minus product cost; excludes operating costs
          </p>
        </div>
        <div className="rounded-lg border border-zinc-800 p-4">
          <dt className="text-sm text-zinc-500">Gross Margin $</dt>
          <dd className="text-xl font-mono mt-1">
            {m ? `$${fmt(m.gross_margin)}` : "—"}
          </dd>
        </div>
        <div className="rounded-lg border border-zinc-800 p-4">
          <dt className="text-sm text-zinc-500">Revenue</dt>
          <dd className="text-xl font-mono mt-1">
            {m ? `$${fmt(m.sale_revenue)}` : "—"}
          </dd>
        </div>
      </div>

      {/* Churn status */}
      <h3 className="text-xl font-bold mb-4">Churn Status</h3>
      <div className="rounded-lg border border-zinc-800 p-4 mb-2">
        <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
          <div>
            <span className="text-zinc-500">Last sale: </span>
            <span className="font-mono">{c?.last_sale_date ?? "—"}</span>
          </div>
          <div>
            <span className="text-zinc-500">Avg days between orders: </span>
            <span className="font-mono">
              {c?.avg_days_between_orders != null
                ? c.avg_days_between_orders.toFixed(0)
                : "—"}
            </span>
          </div>
          <div>
            <span className="text-zinc-500">Days since last sale: </span>
            <span className="font-mono">{c?.days_since_last_sale ?? "—"}</span>
          </div>
          <div>
            <span className="text-zinc-500">Status: </span>
            <span className={`font-semibold ${churnColor}`}>{churnLabel}</span>
          </div>
        </div>
      </div>
      <p className="text-xs text-zinc-600 mb-10">
        Days since last sale is measured to the dataset&apos;s last date (June
        2026), not today.
      </p>

      {/* Monthly revenue chart */}
      <h3 className="text-xl font-bold mb-4">Monthly Revenue</h3>
      <div className="mb-10">
        <RevenueChart data={monthlyRows} />
      </div>

      {/* Product basket */}
      <h3 className="text-xl font-bold mb-4">Product Basket</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-700 text-zinc-400">
              <th className="py-2 text-left font-medium">Product</th>
              <th className="py-2 text-right font-medium">UPC</th>
              <th className="py-2 text-right font-medium">Sales $</th>
              <th className="py-2 text-right font-medium">Net $</th>
              <th className="py-2 text-right font-medium">Sale Units</th>
            </tr>
          </thead>
          <tbody>
            {basketRows.map((r) => (
              <tr key={r.upc} className="border-b border-zinc-800">
                <td className="py-2 font-mono">{r.product_name}</td>
                <td className="py-2 text-right font-mono">{r.upc}</td>
                <td className="py-2 text-right font-mono">{fmt(r.sale_dollars)}</td>
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
