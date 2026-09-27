import { create } from "zustand";

export type BrowserNavigationRequest = { url: string; nonce: number };

interface BrowserNavigationState {
  requests: Record<string, BrowserNavigationRequest>;
  requestNavigation: (browserId: string, url: string) => void;
  clearNavigation: (browserId: string, nonce: number) => void;
}

export const useBrowserNavigationStore = create<BrowserNavigationState>()(
  (set) => ({
    requests: {},
    requestNavigation: (browserId, url) =>
      set((state) => ({
        requests: {
          ...state.requests,
          [browserId]: {
            url,
            nonce: (state.requests[browserId]?.nonce ?? 0) + 1,
          },
        },
      })),
    clearNavigation: (browserId, nonce) =>
      set((state) => {
        if (state.requests[browserId]?.nonce !== nonce) return state;
        const { [browserId]: _cleared, ...requests } = state.requests;
        return { requests };
      }),
  }),
);
