import type { SupportTicketListOptions } from "@posthog/api-client/posthog-client";

export const supportKeys = {
  all: ["support"] as const,
  ticketLists: () => [...supportKeys.all, "ticket-list"] as const,
  ticketList: (options: SupportTicketListOptions) =>
    [...supportKeys.ticketLists(), options] as const,
  ticketListInfinite: (options: SupportTicketListOptions) =>
    [...supportKeys.ticketLists(), "infinite", options] as const,
  ticketDetail: (ticketId: string) =>
    [...supportKeys.all, "ticket-detail", ticketId] as const,
  thread: (ticketId: string) =>
    [...supportKeys.all, "thread", ticketId] as const,
  activity: (ticketId: string) =>
    [...supportKeys.all, "activity", ticketId] as const,
  views: () => [...supportKeys.all, "views"] as const,
};
