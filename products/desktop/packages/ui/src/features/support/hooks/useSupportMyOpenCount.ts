import { useSupportTickets } from "@posthog/ui/features/support/hooks/useSupportTickets";
import { QUEUE_STATUSES } from "@posthog/ui/features/support/supportQueueStore";

export function useSupportMyOpenCount(options?: { enabled?: boolean }) {
  const { data } = useSupportTickets(
    { assignee: ["me"], status: QUEUE_STATUSES, limit: 1 },
    { enabled: options?.enabled ?? true },
  );
  return data?.count ?? 0;
}
