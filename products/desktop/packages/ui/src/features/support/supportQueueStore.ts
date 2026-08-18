import type { Schemas } from "@posthog/api-client";
import type { SupportTicketOrderBy } from "@posthog/api-client/posthog-client";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export const QUEUE_STATUSES: Schemas.TicketStatusEnum[] = [
  "new",
  "open",
  "pending",
  "on_hold",
];

export type SupportAssigneeScope = "me" | "unassigned" | "all";
export type SupportSidebarTab = "ticket" | "agent";
export type SupportComposerMode = "reply" | "note";

interface SupportQueueState {
  assigneeScope: SupportAssigneeScope;
  orderBy: SupportTicketOrderBy;
  search: string;
  viewShortId: string | null;
  sidebarTab: SupportSidebarTab;
  composerMode: SupportComposerMode;
  listWidth: number;
  sidebarWidth: number;
}

interface SupportQueueActions {
  setAssigneeScope(scope: SupportAssigneeScope): void;
  setOrderBy(orderBy: SupportTicketOrderBy): void;
  setSearch(search: string): void;
  setViewShortId(viewShortId: string | null): void;
  setSidebarTab(tab: SupportSidebarTab): void;
  setComposerMode(mode: SupportComposerMode): void;
  setListWidth(width: number): void;
  setSidebarWidth(width: number): void;
}

type SupportQueueStore = SupportQueueState & SupportQueueActions;

const DEFAULT_STATE: SupportQueueState = {
  assigneeScope: "me",
  orderBy: "-updated_at",
  search: "",
  viewShortId: null,
  sidebarTab: "ticket",
  composerMode: "reply",
  listWidth: 280,
  sidebarWidth: 400,
};

export const useSupportQueueStore = create<SupportQueueStore>()(
  persist(
    (set) => ({
      ...DEFAULT_STATE,
      setAssigneeScope: (assigneeScope) => set({ assigneeScope }),
      setOrderBy: (orderBy) => set({ orderBy }),
      setSearch: (search) => set({ search }),
      setViewShortId: (viewShortId) => set({ viewShortId }),
      setSidebarTab: (sidebarTab) => set({ sidebarTab }),
      setComposerMode: (composerMode) => set({ composerMode }),
      setListWidth: (listWidth) => set({ listWidth }),
      setSidebarWidth: (sidebarWidth) => set({ sidebarWidth }),
    }),
    {
      name: "support-queue-storage",
      partialize: (state) => ({
        orderBy: state.orderBy,
        sidebarTab: state.sidebarTab,
        listWidth: state.listWidth,
        sidebarWidth: state.sidebarWidth,
      }),
    },
  ),
);
