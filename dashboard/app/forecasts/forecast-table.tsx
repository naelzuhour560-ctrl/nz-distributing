"use client";

import { useMemo, useState } from "react";
import type { ForecastRow, RouteRow } from "./page";

interface Props {
  rows: ForecastRow[];
  routes: RouteRow[];
}

interface StoreGroup {
  key: string;
  storeName: string;
  locationId: number;
  items: ForecastRow[];
  totalPredicted: number;
  totalSuggested: number;
}

const ALL = "all";

// Below half a unit, round down to no order rather than up to one. Plain
// ceil() turned every faint signal into a unit of stock, which systematically
// over-orders exactly the slowest-moving pairs. Rows that land on 0 are still
// listed — the prediction is information even when the order is nothing.
function suggestedOrder(predicted: number) {
  return predicted < 0.5 ? 0 : Math.ceil(predicted);
}

export default function ForecastTable({ rows, routes }: Props) {
  const [route, setRoute] = useState<string>(ALL);

  const routeName = useMemo(() => {
    const byId = new Map(routes.map((r) => [r.location_id, r.route_name]));
    return (id: number) => byId.get(id) ?? `Route ${id}`;
  }, [routes]);

  // Route tabs come from the forecast rows, not the routes table — a route
  // with no forecasts should not offer a tab that renders an empty page.
  const routeOptions = useMemo(() => {
    const counts = new Map<number, number>();
    for (const r of rows) {
      counts.set(r.location_id, (counts.get(r.location_id) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .map(([locationId, count]) => ({ locationId, count }))
      .sort((a, b) => routeName(a.locationId).localeCompare(routeName(b.locationId)));
  }, [rows, routeName]);

  const groups = useMemo<StoreGroup[]>(() => {
    const filtered =
      route === ALL
        ? rows
        : rows.filter((r) => String(r.location_id) === route);

    const byStore = new Map<string, StoreGroup>();
    for (const r of filtered) {
      const key = `${r.location_id}|${r.store_name}`;
      let group = byStore.get(key);
      if (!group) {
        group = {
          key,
          storeName: r.store_name,
          locationId: r.location_id,
          items: [],
          totalPredicted: 0,
          totalSuggested: 0,
        };
        byStore.set(key, group);
      }
      group.items.push(r);
      group.totalPredicted += r.predicted_units;
      group.totalSuggested += suggestedOrder(r.predicted_units);
    }

    for (const group of byStore.values()) {
      group.items.sort((a, b) => b.predicted_units - a.predicted_units);
    }

    return Array.from(byStore.values()).sort((a, b) =>
      a.storeName.localeCompare(b.storeName)
    );
  }, [rows, route]);

  const shownForecasts = groups.reduce((n, g) => n + g.items.length, 0);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button
          onClick={() => setRoute(ALL)}
          className={`rounded px-3 py-1.5 text-sm font-medium ${
            route === ALL
              ? "bg-blue-600 text-white"
              : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
          }`}
        >
          All routes ({rows.length.toLocaleString()})
        </button>
        {routeOptions.map(({ locationId, count }) => (
          <button
            key={locationId}
            onClick={() => setRoute(String(locationId))}
            className={`rounded px-3 py-1.5 text-sm font-medium ${
              route === String(locationId)
                ? "bg-blue-600 text-white"
                : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
            }`}
          >
            {routeName(locationId)} ({count.toLocaleString()})
          </button>
        ))}
      </div>

      <p className="mb-6 text-sm text-zinc-500">
        {groups.length.toLocaleString()} stores ·{" "}
        {shownForecasts.toLocaleString()} forecasts shown
      </p>

      {groups.length === 0 ? (
        <p className="text-sm text-zinc-500">No forecasts for this route.</p>
      ) : (
        <div className="space-y-8">
          {groups.map((group) => (
            <section key={group.key}>
              <h3 className="mb-2 flex flex-wrap items-baseline gap-x-3 text-lg font-semibold">
                {group.storeName}
                <span className="font-mono text-xs font-normal text-zinc-500">
                  {routeName(group.locationId)}
                </span>
                <span className="text-xs font-normal text-zinc-500">
                  {group.items.length} products · suggested{" "}
                  {group.totalSuggested.toLocaleString()} units
                </span>
              </h3>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-zinc-700 text-zinc-400">
                      <th className="py-2 text-left font-medium">Product</th>
                      <th className="py-2 text-right font-medium">
                        Predicted units
                      </th>
                      <th className="py-2 text-right font-medium">
                        Suggested order
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.items.map((item) => {
                      const suggested = suggestedOrder(item.predicted_units);
                      return (
                        <tr
                          key={`${group.key}|${item.upc}`}
                          className="border-b border-zinc-800"
                        >
                          <td className="py-2">
                            {item.product_name}
                            <span className="ml-2 font-mono text-xs text-zinc-600">
                              {item.upc}
                            </span>
                          </td>
                          <td className="py-2 text-right font-mono">
                            {item.predicted_units.toFixed(1)}
                          </td>
                          <td
                            className={`py-2 text-right font-mono font-semibold ${
                              suggested === 0 ? "text-zinc-600" : ""
                            }`}
                          >
                            {suggested.toLocaleString()}
                          </td>
                        </tr>
                      );
                    })}
                    <tr className="text-zinc-400">
                      <td className="py-2 text-right text-xs uppercase tracking-wide">
                        Store total
                      </td>
                      <td className="py-2 text-right font-mono">
                        {group.totalPredicted.toFixed(1)}
                      </td>
                      <td className="py-2 text-right font-mono font-semibold">
                        {group.totalSuggested.toLocaleString()}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
