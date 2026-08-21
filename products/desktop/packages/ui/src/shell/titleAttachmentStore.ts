import { create } from "zustand";

/**
 * Local attachment file paths captured at task-creation time, keyed by task id,
 * so the chat-title generator can read their contents when naming a task.
 *
 * Why this exists: when a prompt is pasted as a text file (or otherwise sent as
 * an attachment with no typed text), the title has to come from the file's
 * contents. For local tasks the prompt event still carries the `<file .../>`
 * path, so the generator can read it directly. For cloud tasks it cannot — the
 * stored description is reduced to `Attached files: <name>` and the echoed
 * prompt event points at the remote sandbox path (e.g.
 * `file:///workspace/.posthog/attachments/...`), which is not readable on the
 * user's machine. The only place the original local path exists is at submit
 * time, so we stash it here and hand it to the generator, which reads the file
 * locally before it is cleaned up.
 *
 * Best-effort and in-memory: lost on reload, at which point the title falls back
 * to the attachment summary.
 */
interface TitleAttachmentStore {
  byTaskId: Record<string, string[]>;
  set: (taskId: string, filePaths: string[]) => void;
  get: (taskId: string) => string[] | undefined;
  clear: (taskId: string) => void;
}

const useTitleAttachmentStore = create<TitleAttachmentStore>((set, get) => ({
  byTaskId: {},
  set: (taskId, filePaths) =>
    set((state) => ({
      byTaskId: { ...state.byTaskId, [taskId]: filePaths },
    })),
  get: (taskId) => get().byTaskId[taskId],
  clear: (taskId) =>
    set((state) => {
      if (!(taskId in state.byTaskId)) return state;
      const { [taskId]: _removed, ...rest } = state.byTaskId;
      return { byTaskId: rest };
    }),
}));

export const titleAttachmentStoreApi = {
  set: (taskId: string, filePaths: string[]) =>
    useTitleAttachmentStore.getState().set(taskId, filePaths),
  get: (taskId: string) => useTitleAttachmentStore.getState().get(taskId),
  clear: (taskId: string) => useTitleAttachmentStore.getState().clear(taskId),
};
