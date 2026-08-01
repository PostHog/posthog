import { toast as quillToast } from "@posthog/quill";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";

// Thin wrapper over quill's toast so the whole app shares one import and a
// stable `(title, options)` signature. Quill (base-ui under the hood) owns
// rendering, stacking, auto-dismiss, hover-to-pause, and the close button —
// which is why this exists instead of a hand-rolled custom toast.

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  description?: string;
  // A caller-chosen stable id: upserts (creates or replaces) the toast with
  // that id so it never stacks. quill itself can't
  // pick an id at create time, so the wrapper maps it (see idRegistry).
  id?: string;
  action?: ToastAction;
  // Auto-dismiss delay in ms. Maps to quill's `timeout`. Omit for the provider
  // default; loading toasts never auto-dismiss regardless.
  duration?: number;
}

// The second argument may be a bare description string (shorthand) or the full
// options object.
type Detail = string | ToastOptions;

type Level = "success" | "error" | "info" | "warning" | "loading";

// Maps a caller-chosen stable id → quill's generated id, so `{ id }` behaves as
// an upsert: the first call creates a quill toast and records the mapping; a
// repeat call (or a different level) updates that same toast instead of
// stacking; `dismiss(id)` resolves through here. Entries self-clean on close.
const idRegistry = new Map<string, string>();

function normalize(detail?: Detail): ToastOptions {
  return typeof detail === "string" ? { description: detail } : (detail ?? {});
}

function emit(
  level: Level,
  title: string,
  detail: Detail | undefined,
  defaultTimeout?: number,
): string | undefined {
  const o = normalize(detail);
  // Toasts can be disabled in settings; errors always show since they carry
  // information the user needs regardless of that preference.
  if (level !== "error" && !useSettingsStore.getState().toastNotifications) {
    return o.id;
  }
  // base-ui auto-dismisses any non-loading toast with `timeout > 0`; it has no
  // Infinity special-case (Infinity would fire immediately), so a request to
  // never auto-dismiss maps to `0`.
  const requested = o.duration ?? defaultTimeout;
  const timeout = requested === Number.POSITIVE_INFINITY ? 0 : requested;
  const fields = {
    title,
    description: o.description,
    timeout,
    action: o.action,
  };

  if (o.id !== undefined) {
    const stableId = o.id;
    const existing = idRegistry.get(stableId);
    if (existing !== undefined) {
      quillToast.update(existing, { type: level, ...fields });
      return stableId;
    }
    const quillId = quillToast[level]({
      ...fields,
      onClose: () => {
        if (idRegistry.get(stableId) === quillId) idRegistry.delete(stableId);
      },
    });
    idRegistry.set(stableId, quillId);
    return stableId;
  }

  return quillToast[level](fields);
}

export const toast = {
  success: (title: string, detail?: Detail) => emit("success", title, detail),
  // Errors linger a touch longer than the default, matching prior behavior.
  error: (title: string, detail?: Detail) => emit("error", title, detail, 5000),
  info: (title: string, detail?: Detail) => emit("info", title, detail),
  warning: (title: string, detail?: Detail) => emit("warning", title, detail),
  loading: (title: string, detail?: Detail) => emit("loading", title, detail),
  dismiss: (id?: string) => {
    if (id === undefined) return;
    quillToast.dismiss(idRegistry.get(id) ?? id);
    idRegistry.delete(id);
  },
};
