import { supabase } from "@/lib/supabase";
import ReminderList from "./reminder-list";

export const dynamic = "force-dynamic";

export interface TopProduct {
  upc: string;
  product_name: string;
  predicted_units: number;
}

export interface ReminderRow {
  id: number;
  location_id: number;
  store_name: string;
  week_start: string;
  draft_message: string;
  top_products: TopProduct[];
  predicted_total_units: number;
  status: string;
  generated_at: string;
  approved_at: string | null;
}

export interface RouteRow {
  location_id: number;
  route_name: string;
}

// PostgREST caps a response at 1,000 rows regardless of the range requested.
// One week fits comfortably today, but the cap is silent — it returns a short
// page rather than an error — so page through it rather than trusting the fit.
const PAGE_SIZE = 1000;

async function fetchRemindersForWeek(weekStart: string): Promise<ReminderRow[]> {
  const rows: ReminderRow[] = [];
  let offset = 0;

  for (;;) {
    const { data, error } = await supabase
      .from("reminders")
      .select("*")
      .eq("week_start", weekStart)
      .order("predicted_total_units", { ascending: false })
      .range(offset, offset + PAGE_SIZE - 1);

    if (error) throw new Error(`Could not load reminders: ${error.message}`);

    const page = (data ?? []) as ReminderRow[];
    if (page.length === 0) break;

    rows.push(...page);
    offset += page.length;
  }

  return rows;
}

export default async function RemindersPage() {
  const [{ data: latest }, { data: routeData }] = await Promise.all([
    supabase
      .from("reminders")
      .select("week_start")
      .order("week_start", { ascending: false })
      .limit(1),
    supabase.from("routes").select("location_id,route_name"),
  ]);

  const weekStart =
    (latest as { week_start: string }[] | null)?.[0]?.week_start ?? null;
  const routes = (routeData ?? []) as RouteRow[];
  const reminders = weekStart ? await fetchRemindersForWeek(weekStart) : [];

  const counts = reminders.reduce<Record<string, number>>((acc, r) => {
    acc[r.status] = (acc[r.status] ?? 0) + 1;
    return acc;
  }, {});

  const STATUS_ORDER = ["draft", "approved", "sent"];
  const orderedCounts = [
    ...STATUS_ORDER.filter((s) => counts[s]),
    ...Object.keys(counts).filter((s) => !STATUS_ORDER.includes(s)).sort(),
  ];

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Reorder Reminders</h2>
      <p className="text-sm text-zinc-500 mb-1">
        Week starting{" "}
        <span className="font-mono text-zinc-300">{weekStart ?? "—"}</span> ·{" "}
        {reminders.length.toLocaleString()} reminders
        {orderedCounts.length > 0 && (
          <>
            {" — "}
            {orderedCounts.map((status, i) => (
              <span key={status}>
                {i > 0 && ", "}
                <span className="font-mono text-zinc-300">
                  {counts[status]}
                </span>{" "}
                {status}
              </span>
            ))}
          </>
        )}
      </p>
      <p className="text-sm text-zinc-500 mb-6 max-w-3xl">
        Drafts are written by a model from next week&apos;s forecast and are{" "}
        <span className="font-medium text-zinc-400">
          never sent from this dashboard
        </span>
        . Read each one before approving. &ldquo;Mark sent&rdquo; records that
        you sent it yourself — it does not deliver anything.
      </p>

      {reminders.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No reminders yet. Run{" "}
          <span className="font-mono">scripts/generate_reminders.py</span> to
          create drafts for the current forecast week.
        </p>
      ) : (
        <ReminderList reminders={reminders} routes={routes} />
      )}
    </div>
  );
}
