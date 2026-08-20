"use client";

import { useState, useTransition } from "react";
import { approveReminder, markReminderSent } from "./actions";
import type { ReminderRow, RouteRow } from "./page";

interface Props {
  reminders: ReminderRow[];
  routes: RouteRow[];
}

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-zinc-800 text-zinc-300",
  approved: "bg-green-900/60 text-green-300",
  sent: "bg-blue-900/60 text-blue-300",
};

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? "bg-amber-900/60 text-amber-300";
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-medium uppercase tracking-wide ${style}`}
    >
      {status}
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  async function copy() {
    try {
      // Unavailable outside a secure context (plain http on a LAN address),
      // so surface the failure rather than silently doing nothing.
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setFailed(false);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setFailed(true);
    }
  }

  return (
    <button
      onClick={copy}
      className="rounded bg-zinc-800 px-2 py-1 text-xs font-medium text-zinc-300 hover:bg-zinc-700"
    >
      {failed ? "Copy failed — select manually" : copied ? "Copied" : "Copy"}
    </button>
  );
}

function ReminderCard({
  reminder,
  routeName,
}: {
  reminder: ReminderRow;
  routeName: string;
}) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function run(action: () => Promise<void>) {
    setError(null);
    startTransition(async () => {
      try {
        await action();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Something went wrong");
      }
    });
  }

  return (
    <section className="rounded-lg border border-zinc-800 p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="flex flex-wrap items-baseline gap-x-3 text-lg font-semibold">
          {reminder.store_name}
          <span className="font-mono text-xs font-normal text-zinc-500">
            {routeName}
          </span>
        </h3>
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm text-zinc-400">
            {reminder.predicted_total_units.toLocaleString(undefined, {
              maximumFractionDigits: 1,
            })}{" "}
            units forecast
          </span>
          <StatusBadge status={reminder.status} />
        </div>
      </div>

      <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
        {reminder.top_products.map((p) => (
          <li key={p.upc}>
            {p.product_name}{" "}
            <span className="font-mono text-zinc-600">
              {p.predicted_units.toLocaleString(undefined, {
                maximumFractionDigits: 1,
              })}
            </span>
          </li>
        ))}
      </ul>

      <div className="mb-3">
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs uppercase tracking-wide text-zinc-500">
            Draft message
          </span>
          <CopyButton text={reminder.draft_message} />
        </div>
        <pre className="overflow-x-auto whitespace-pre-wrap rounded border border-zinc-800 bg-zinc-900/60 p-3 font-sans text-sm text-zinc-200">
          {reminder.draft_message}
        </pre>
        <p className="mt-1 text-xs text-zinc-600">
          {reminder.draft_message.length} characters
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => run(() => approveReminder(reminder.id))}
          disabled={pending || reminder.status === "approved"}
          className="rounded bg-green-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Approve
        </button>
        <button
          onClick={() => run(() => markReminderSent(reminder.id))}
          disabled={pending || reminder.status === "sent"}
          className="rounded bg-blue-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Mark sent
        </button>
        {pending && <span className="text-xs text-zinc-500">Saving…</span>}
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>
    </section>
  );
}

export default function ReminderList({ reminders, routes }: Props) {
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const routeName = (id: number) =>
    routes.find((r) => r.location_id === id)?.route_name ?? `Route ${id}`;

  const statuses = Array.from(new Set(reminders.map((r) => r.status))).sort();
  const shown =
    statusFilter === "all"
      ? reminders
      : reminders.filter((r) => r.status === statusFilter);

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <button
          onClick={() => setStatusFilter("all")}
          className={`rounded px-3 py-1.5 text-sm font-medium ${
            statusFilter === "all"
              ? "bg-blue-600 text-white"
              : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
          }`}
        >
          All ({reminders.length})
        </button>
        {statuses.map((status) => (
          <button
            key={status}
            onClick={() => setStatusFilter(status)}
            className={`rounded px-3 py-1.5 text-sm font-medium ${
              statusFilter === status
                ? "bg-blue-600 text-white"
                : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
            }`}
          >
            {status} ({reminders.filter((r) => r.status === status).length})
          </button>
        ))}
      </div>

      <div className="space-y-4">
        {shown.map((reminder) => (
          <ReminderCard
            key={reminder.id}
            reminder={reminder}
            routeName={routeName(reminder.location_id)}
          />
        ))}
      </div>
    </div>
  );
}
