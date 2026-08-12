import type { SupportTicketListOptions } from "@posthog/api-client/posthog-client";

/**
 * Lists and ticket details sit in separate key namespaces on purpose. Reading a
 * ticket clears its unread count for the whole team, so a list invalidation must
 * not reach the open ticket's entry by prefix and silently refetch it.
 */
export const supportKeys = {
  all: ["support"] as const,
  ticketLists: () => [...supportKeys.all, "ticket-list"] as const,
  ticketList: (options: SupportTicketListOptions) =>
    [...supportKeys.ticketLists(), options] as const,
  ticketDetails: () => [...supportKeys.all, "ticket-detail"] as const,
  ticketDetail: (idOrNumber: string) =>
    [...supportKeys.ticketDetails(), idOrNumber] as const,
  threads: () => [...supportKeys.all, "thread"] as const,
  thread: (ticketId: string) => [...supportKeys.threads(), ticketId] as const,
  unreadCount: () => [...supportKeys.all, "unread-count"] as const,
  views: () => [...supportKeys.all, "views"] as const,
};
