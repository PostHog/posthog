import { beforeEach, describe, expect, it, vi } from "vitest";

const quill = vi.hoisted(() => {
  let n = 0;
  const make = () =>
    vi.fn(
      (_opts?: { onClose?: () => void } & Record<string, unknown>) => `q${++n}`,
    );
  return {
    success: make(),
    error: make(),
    info: make(),
    warning: make(),
    loading: make(),
    update: vi.fn(),
    dismiss: vi.fn(),
    _reset: () => {
      n = 0;
    },
  };
});

vi.mock("@posthog/quill", () => ({ toast: quill }));

const settings = vi.hoisted(() => ({ toastNotifications: true }));

vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  useSettingsStore: { getState: () => settings },
}));

import { useErrorDetailsStore } from "@posthog/ui/features/notifications/errorDetailsStore";
import { toast } from "./toast";

beforeEach(() => {
  vi.clearAllMocks();
  quill._reset();
  settings.toastNotifications = true;
  useErrorDetailsStore.getState().close();
  // clearAllMocks resets the level fns to undefined returns; restore ids.
  let n = 0;
  for (const key of [
    "success",
    "error",
    "info",
    "warning",
    "loading",
  ] as const) {
    quill[key].mockImplementation(() => `q${++n}`);
  }
});

describe("toast wrapper", () => {
  it("creates without an id and forwards title/description/timeout", () => {
    toast.success("Saved", { description: "All good", duration: 1000 });
    expect(quill.success).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Saved",
        description: "All good",
        timeout: 1000,
      }),
    );
    expect(quill.update).not.toHaveBeenCalled();
  });

  it("upserts a stable id: first call creates, repeat call updates the same toast", () => {
    // Regression: a fresh caller-chosen id must CREATE (not no-op via update).
    toast.success("Task archived", { id: "archive-1" });
    expect(quill.success).toHaveBeenCalledTimes(1);
    expect(quill.update).not.toHaveBeenCalled();

    toast.error("Now failed", { id: "archive-1" });
    // Same id → updates the previously-created quill toast, no new create.
    expect(quill.error).not.toHaveBeenCalled();
    expect(quill.update).toHaveBeenCalledWith(
      "q1",
      expect.objectContaining({ type: "error", title: "Now failed" }),
    );
  });

  it("dismiss(stableId) resolves through the registry to the quill id", () => {
    toast.success("Archived", { id: "archive-2" });
    toast.dismiss("archive-2");
    expect(quill.dismiss).toHaveBeenCalledWith("q1");
  });

  it("dismiss falls back to the raw id for unregistered (loading-returned) ids", () => {
    const id = toast.loading("Working…"); // returns the raw quill id
    toast.dismiss(id);
    expect(quill.dismiss).toHaveBeenCalledWith(id);
  });

  it("maps duration Infinity to timeout 0 (base-ui 'never auto-dismiss')", () => {
    toast.error("Offline", { duration: Number.POSITIVE_INFINITY });
    expect(quill.error).toHaveBeenCalledWith(
      expect.objectContaining({ timeout: 0 }),
    );
  });

  it.each(["success", "info", "warning", "loading"] as const)(
    "suppresses %s when toast notifications are disabled",
    (level) => {
      settings.toastNotifications = false;
      toast[level]("Title");
      expect(quill[level]).not.toHaveBeenCalled();
    },
  );

  it("always shows error toasts, even when toast notifications are disabled", () => {
    settings.toastNotifications = false;
    toast.error("Offline");
    expect(quill.error).toHaveBeenCalled();
  });

  it("adds View larger to a bare error toast and shows its title", () => {
    toast.error("Failed request");

    const options = quill.error.mock.calls[0]?.[0] as {
      action: { label: string; onClick: () => void };
    };
    expect(options.action.label).toBe("View larger");
    options.action.onClick();
    expect(useErrorDetailsStore.getState().detail).toEqual(
      expect.objectContaining({
        title: "Failed request",
        error: "Failed request",
      }),
    );
  });

  it("shows the complete error payload instead of its toast summary", () => {
    const error = { status: 400, body: { detail: "Invalid request" } };
    toast.error("Failed request", {
      description: "Invalid request",
      error,
    });

    const options = quill.error.mock.calls[0]?.[0] as {
      action: { label: string; onClick: () => void };
    };
    options.action.onClick();
    expect(useErrorDetailsStore.getState().detail).toEqual(
      expect.objectContaining({ title: "Failed request", error }),
    );
  });

  it("replaces a caller action so error toasts always offer View larger", () => {
    const callerAction = vi.fn();
    toast.error("Failed request", {
      action: { label: "Retry", onClick: callerAction },
    });

    const options = quill.error.mock.calls[0]?.[0] as {
      action: { label: string; onClick: () => void };
    };
    expect(options.action.label).toBe("View larger");
    options.action.onClick();
    expect(callerAction).not.toHaveBeenCalled();
  });

  it("opens the latest payload after a stable error toast is updated", () => {
    toast.error("First failure", {
      id: "updated-error",
      error: { message: "first" },
    });
    const latestError = { message: "second" };
    toast.error("Second failure", {
      id: "updated-error",
      error: latestError,
    });

    const update = quill.update.mock.calls[0]?.[1] as {
      action: { label: string; onClick: () => void };
    };
    expect(update.action.label).toBe("View larger");
    update.action.onClick();
    expect(useErrorDetailsStore.getState().detail).toEqual(
      expect.objectContaining({ title: "Second failure", error: latestError }),
    );
  });

  it.each([
    [undefined, undefined],
    ["stable-id", "stable-id"],
  ])(
    "returns %s (not a fabricated id) when suppressed with detail id %s",
    (id, expected) => {
      settings.toastNotifications = false;
      expect(toast.success("Title", id ? { id } : undefined)).toBe(expected);
    },
  );

  it("after a toast closes, its id frees up to create again", () => {
    toast.success("First", { id: "dup" });
    quill.success.mock.calls[0]?.[0]?.onClose?.(); // simulate the toast closing
    toast.success("Second", { id: "dup" });
    // Recreated (two creates), not updated.
    expect(quill.success).toHaveBeenCalledTimes(2);
    expect(quill.update).not.toHaveBeenCalled();
  });
});
