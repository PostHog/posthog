import { create } from "zustand";

export interface TaskInputReportAssociation {
  reportId: string;
  title: string;
}

export interface TaskInputPrefill {
  requestId?: string;
  folderId?: string;
  initialPrompt?: string;
  initialCloudRepository?: string;
  initialModel?: string;
  initialMode?: string;
  folderRunEnvironment?: "local" | "cloud";
  reportAssociation?: TaskInputReportAssociation;
}

interface PrefillStoreState {
  prefill: TaskInputPrefill;
  setPrefill: (prefill: TaskInputPrefill) => void;
  clearReportAssociation: () => void;
  clear: () => void;
}

// Holds transient state used to prefill the TaskInput screen when navigation
// is triggered with options (e.g. deep links, "discuss in new task" flows).
// Lives outside the URL because the values are large/structured and don't
// belong in a hash fragment.
export const useTaskInputPrefillStore = create<PrefillStoreState>((set) => ({
  prefill: {},
  setPrefill: (prefill) => set({ prefill }),
  clearReportAssociation: () =>
    set((s) => ({
      prefill: {
        ...s.prefill,
        reportAssociation: undefined,
        initialCloudRepository: undefined,
      },
    })),
  clear: () => set({ prefill: {} }),
}));
