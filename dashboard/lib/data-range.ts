import { supabase } from "./supabase";

/**
 * The date span actually present in invoice_lines.
 *
 * Pages used to state this as literal text ("Jan 2025 – Jun 2026"), which went
 * wrong the moment the data was reloaded and silently mislabelled every figure
 * on the page. Read it from the data instead.
 */
export interface DataRange {
  minDate: string | null;
  maxDate: string | null;
  /** "Jan 2025 – Aug 2026", or "the loaded period" when the table is empty. */
  label: string;
  /** "17 Aug 2026", or "—" when the table is empty. */
  lastDate: string;
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

// Formatted off the ISO string directly. Going via Date would re-interpret
// "2026-08-17" as UTC midnight and could render the previous day once the
// server's timezone is applied.
function monthYear(iso: string) {
  const [year, month] = iso.split("-");
  return `${MONTHS[Number(month) - 1]} ${year}`;
}

function fullDate(iso: string) {
  const [year, month, day] = iso.split("-");
  return `${Number(day)} ${MONTHS[Number(month) - 1]} ${year}`;
}

async function edgeDate(ascending: boolean): Promise<string | null> {
  const { data } = await supabase
    .from("invoice_lines")
    .select("calendar_date")
    .order("calendar_date", { ascending })
    .limit(1);

  return (data as { calendar_date: string }[] | null)?.[0]?.calendar_date ?? null;
}

export async function getDataRange(): Promise<DataRange> {
  const [minDate, maxDate] = await Promise.all([edgeDate(true), edgeDate(false)]);

  return {
    minDate,
    maxDate,
    label:
      minDate && maxDate
        ? `${monthYear(minDate)} – ${monthYear(maxDate)}`
        : "the loaded period",
    lastDate: maxDate ? fullDate(maxDate) : "—",
  };
}
