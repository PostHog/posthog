import type { SupportTicketListOptions } from "@posthog/api-client/posthog-client";

// Lists and details are separate namespaces: reading a ticket clears its unread
// count team-wide, so a list invalidation must not reach the open ticket.
export const supportKeys = {
  all: ["support"] as const,
  ticketLists: () => [...supportKeys.all, "ticket-list"] as const,
  ticketList: (options: SupportTicketListOptions) =>
    [...supportKeys.ticketLists(), options] as const,
  ticketDetail: (ticketId: string) =>
    [...supportKeys.all, "ticket-detail", ticketId] as const,
  thread: (ticketId: string) =>
    [...supportKeys.all, "thread", ticketId] as const,
  unreadCount: () => [...supportKeys.all, "unread-count"] as const,
  views: () => [...supportKeys.all, "views"] as const,
};
