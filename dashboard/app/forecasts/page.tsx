import { supabase } from "@/lib/supabase";
import ForecastTable from "./forecast-table";

export const dynamic = "force-dynamic";

export interface ForecastRow {
  location_id: number;
  store_name: string;
  upc: string;
  product_name: string;
  week_start: string;
  predicted_units: number;
}

export interface RouteRow {
  location_id: number;
  route_name: string;
}

// PostgREST caps a response at 1,000 rows regardless of the range requested, so
// a single .rpc() call silently returns the first page rather than the whole
// forecast. Page through it.
const PAGE_SIZE = 1000;

async function fetchAllForecasts(): Promise<ForecastRow[]> {
  const rows: ForecastRow[] = [];
  let offset = 0;

  for (;;) {
    const { data, error } = await supabase
      .rpc("forecast_next_week")
      .range(offset, offset + PAGE_SIZE - 1);

    if (error) throw new Error(`forecast_next_week failed: ${error.message}`);

    const page = (data ?? []) as ForecastRow[];
    if (page.length === 0) break;

    rows.push(...page);
    offset += page.length;
  }

  return rows;
}

export default async function ForecastsPage() {
  const [rows, { data: routeData }] = await Promise.all([
    fetchAllForecasts(),
    supabase.from("routes").select("location_id,route_name"),
  ]);

  const routes = (routeData ?? []) as RouteRow[];

  const weekStart = rows[0]?.week_start ?? null;

  // The RPC does not expose model_version, so read it from the row it came
  // from rather than hardcoding a string the header would keep showing after
  // the model changed.
  const { data: versionData } = await supabase
    .from("forecasts")
    .select("model_version")
    .eq("week_start", weekStart ?? "")
    .limit(1);

  const modelVersion =
    (versionData as { model_version: string }[] | null)?.[0]?.model_version ??
    "unknown";

  const storeCount = new Set(
    rows.map((r) => `${r.location_id}|${r.store_name}`)
  ).size;

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Next Week Forecast</h2>
      <p className="text-sm text-zinc-500 mb-1">
        Week starting{" "}
        <span className="font-mono text-zinc-300">{weekStart ?? "—"}</span> ·
        model <span className="font-mono text-zinc-300">{modelVersion}</span> ·{" "}
        {rows.length.toLocaleString()} forecasts across {storeCount} stores
      </p>
      <p className="text-sm text-zinc-500 mb-6 max-w-3xl">
        <span className="font-medium text-zinc-400">Suggested order</span>{" "}
        rounds the prediction up to the next whole unit, except below half a
        unit where it drops to zero. Rows suggesting nothing are still listed —
        the prediction is information even when the order is not. Suggestions
        are <span className="font-medium text-zinc-400">unit-rounded, not
        case-rounded</span>: there is no case-size data in the pipeline, so
        these still need converting to whole cases before ordering. Forecasts
        exist only for the {rows.length.toLocaleString()} store-product pairs
        with enough sales history (at least 12 weeks with a sale); anything
        newer or sparser is absent from this page rather than forecast as zero.
      </p>

      <ForecastTable rows={rows} routes={routes} />
    </div>
  );
}
