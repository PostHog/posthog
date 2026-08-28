import type { EditorContent } from "@posthog/core/message-editor/content";
import { create } from "zustand";

export interface TaskInputReportAssociation {
  reportId: string;
  title: string;
}

export interface TaskInputPrefill {
  requestId?: string;
  folderId?: string;
  /** `owner/repo` of the picked sidebar group, for groups with no folder. */
  folderRepository?: string;
  initialPrompt?: string;
  /**
   * Full editor content to restore, including file chips and attachments.
   * Preferred over initialPrompt when set (e.g. recovering an interrupted
   * prompt); initialPrompt stays for plain-text callers.
   */
  initialContent?: EditorContent;
  /**
   * Pending-prompt record key this prefill was recovered from. The composer
   * clears that record once it applies the content, so the durable record
   * outlives the transient prefill until the prompt is safely in the composer.
   */
  recoveredFromKey?: string;
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
  /**
   * Retire a prompt once the composer has applied it. Without this the prompt
   * outlives its navigation and is re-applied — over the user's own draft — the
   * next time a new-task screen mounts. Scoped by requestId so a newer prefill
   * that landed in between is left alone.
   */
  consumePrompt: (requestId: string) => void;
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
  consumePrompt: (requestId) =>
    set((s) =>
      s.prefill.requestId === requestId
        ? {
            prefill: {
              ...s.prefill,
              initialPrompt: undefined,
              initialContent: undefined,
              recoveredFromKey: undefined,
              requestId: undefined,
            },
          }
        : s,
    ),
}));
