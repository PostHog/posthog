import type { SupportActivityEntry } from "@posthog/api-client/posthog-client";
import { supportKeys } from "@posthog/ui/features/support/supportKeys";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

export function useSupportTicketActivity(ticketId: string) {
  return useAuthenticatedQuery<SupportActivityEntry[]>(
    supportKeys.activity(ticketId),
    (client) => client.listSupportTicketActivity(ticketId),
  );
}
