import type { ChannelDocumentKind } from "@posthog/shared/domain-types";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

const DEFAULT_PANEL_WIDTH = 360;

/**
 * View state for the space docs sidepanel — the right dock showing a space's
 * shared todo/plan docs. `channelId` is the backend task-channel id (not the
 * desktop file-system folder id); it is set by whichever surface opened the
 * panel (usually a message-selection capture) so the panel stays pinned to the
 * space the capture landed in even if the user navigates elsewhere.
 */
interface SpaceDocsPanelState {
  open: boolean;
  width: number;
  isResizing: boolean;
  channelId: string | null;
  focusDocKind: ChannelDocumentKind | null;
  openPanel: (input: {
    channelId: string;
    docKind?: ChannelDocumentKind;
  }) => void;
  closePanel: () => void;
  setWidth: (width: number) => void;
  setIsResizing: (isResizing: boolean) => void;
}

export const useSpaceDocsPanelStore = create<SpaceDocsPanelState>()(
  persist(
    (set) => ({
      open: false,
      width: DEFAULT_PANEL_WIDTH,
      isResizing: false,
      channelId: null,
      focusDocKind: null,
      openPanel: ({ channelId, docKind }) =>
        set({ open: true, channelId, focusDocKind: docKind ?? null }),
      closePanel: () => set({ open: false }),
      setWidth: (width) => set({ width }),
      setIsResizing: (isResizing) => set({ isResizing }),
    }),
    {
      name: "space-docs-panel-storage",
      storage: electronStorage,
      partialize: (state) => ({ width: state.width }),
    },
  ),
);
