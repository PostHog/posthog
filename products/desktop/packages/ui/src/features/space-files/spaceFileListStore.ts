import {
  DEFAULT_SPACE_FILE_LIST_SETTINGS,
  type SpaceFileListSettings,
} from "@posthog/core/canvas/spaceFileList";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SpaceFileListState {
  settings: SpaceFileListSettings;
  setSettings: (settings: SpaceFileListSettings) => void;
}

export const useSpaceFileListStore = create<SpaceFileListState>()(
  persist(
    (set) => ({
      settings: DEFAULT_SPACE_FILE_LIST_SETTINGS,
      setSettings: (settings) => set({ settings }),
    }),
    {
      name: "space-file-list",
      storage: electronStorage,
      partialize: (state) => ({ settings: state.settings }),
      merge: (persisted, current) => ({
        ...current,
        settings: {
          ...current.settings,
          ...((persisted as Partial<SpaceFileListState>)?.settings ?? {}),
        },
      }),
    },
  ),
);
