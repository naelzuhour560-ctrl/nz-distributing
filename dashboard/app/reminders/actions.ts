"use server";

import { revalidatePath } from "next/cache";
import { supabase } from "@/lib/supabase";
import { createClient } from "@/lib/supabase-auth-server";

/**
 * Server actions are reachable by direct POST, not only through the UI, so the
 * middleware redirect that guards the page does not guard these. Every action
 * re-checks the session itself before touching a row.
 */
async function requireUser() {
  const authClient = await createClient();
  const {
    data: { user },
  } = await authClient.auth.getUser();

  if (!user) throw new Error("Unauthorized");
  return user;
}

export async function approveReminder(id: number) {
  await requireUser();

  const { error } = await supabase
    .from("reminders")
    .update({ status: "approved", approved_at: new Date().toISOString() })
    .eq("id", id);

  if (error) throw new Error(`Could not approve reminder: ${error.message}`);

  revalidatePath("/reminders");
}

export async function markReminderSent(id: number) {
  await requireUser();

  // Records that a human sent it. Nothing in this app sends messages — this
  // marks work already done elsewhere.
  const { error } = await supabase
    .from("reminders")
    .update({ status: "sent" })
    .eq("id", id);

  if (error) throw new Error(`Could not mark reminder sent: ${error.message}`);

  revalidatePath("/reminders");
}
