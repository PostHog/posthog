import { create } from "zustand";
import { persist } from "zustand/middleware";

interface PinnedTicketsState {
  /** Ticket id → when it was pinned. View state on this machine only, like pinned browser tabs. */
  pinnedAtById: Record<string, number>;
}

interface PinnedTicketsActions {
  togglePinned(ticketId: string): void;
}

type PinnedTicketsStore = PinnedTicketsState & PinnedTicketsActions;

export const usePinnedTicketsStore = create<PinnedTicketsStore>()(
  persist(
    (set) => ({
      pinnedAtById: {},
      togglePinned: (ticketId) =>
        set((state) => {
          const pinnedAtById = { ...state.pinnedAtById };
          if (pinnedAtById[ticketId] === undefined) {
            pinnedAtById[ticketId] = Date.now();
          } else {
            delete pinnedAtById[ticketId];
          }
          return { pinnedAtById };
        }),
    }),
    { name: "support-pinned-tickets" },
  ),
);

export function sortedPinnedTicketIds(
  pinnedAtById: Record<string, number>,
): string[] {
  return Object.entries(pinnedAtById)
    .sort(([, a], [, b]) => b - a)
    .map(([id]) => id);
}
