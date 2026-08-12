import type { Schemas } from "@posthog/api-client";
import type { SupportTicketOrderBy } from "@posthog/api-client/posthog-client";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type SupportAssigneeScope = "me" | "unassigned" | "all";
export type SupportSidebarTab = "ticket" | "agent";
export type SupportComposerMode = "reply" | "note";

interface SupportQueueState {
  assigneeScope: SupportAssigneeScope;
  statuses: Schemas.TicketStatusEnum[];
  orderBy: SupportTicketOrderBy;
  search: string;
  viewShortId: string | null;
  sidebarTab: SupportSidebarTab;
  composerMode: SupportComposerMode;
}

interface SupportQueueActions {
  setAssigneeScope(scope: SupportAssigneeScope): void;
  setStatuses(statuses: Schemas.TicketStatusEnum[]): void;
  setOrderBy(orderBy: SupportTicketOrderBy): void;
  setSearch(search: string): void;
  setViewShortId(viewShortId: string | null): void;
  setSidebarTab(tab: SupportSidebarTab): void;
  setComposerMode(mode: SupportComposerMode): void;
  clearFilters(): void;
}

type SupportQueueStore = SupportQueueState & SupportQueueActions;

const DEFAULT_STATUSES: Schemas.TicketStatusEnum[] = [
  "new",
  "open",
  "pending",
  "on_hold",
];

const DEFAULT_STATE: SupportQueueState = {
  assigneeScope: "me",
  statuses: DEFAULT_STATUSES,
  orderBy: "-updated_at",
  search: "",
  viewShortId: null,
  sidebarTab: "ticket",
  composerMode: "reply",
};

export const useSupportQueueStore = create<SupportQueueStore>()(
  persist(
    (set) => ({
      ...DEFAULT_STATE,
      setAssigneeScope: (assigneeScope) => set({ assigneeScope }),
      setStatuses: (statuses) => set({ statuses }),
      setOrderBy: (orderBy) => set({ orderBy }),
      setSearch: (search) => set({ search }),
      setViewShortId: (viewShortId) => set({ viewShortId }),
      setSidebarTab: (sidebarTab) => set({ sidebarTab }),
      setComposerMode: (composerMode) => set({ composerMode }),
      clearFilters: () =>
        set({
          assigneeScope: DEFAULT_STATE.assigneeScope,
          statuses: DEFAULT_STATE.statuses,
          search: "",
          viewShortId: null,
        }),
    }),
    {
      name: "support-queue-storage",
      // Display only: a persisted scope would silently narrow tomorrow's queue.
      partialize: (state) => ({
        orderBy: state.orderBy,
        sidebarTab: state.sidebarTab,
      }),
    },
  ),
);
