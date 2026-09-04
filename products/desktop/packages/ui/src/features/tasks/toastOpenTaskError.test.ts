import { ApiRequestError } from "@posthog/api-client/fetcher";
import { beforeEach, describe, expect, it, vi } from "vitest";

interface EmittedToast {
  title: string;
  description?: string;
  action?: { label: string; onClick: () => void };
}

const emitted: EmittedToast[] = [];

vi.mock("@posthog/quill", () => ({
  toast: {
    error: (fields: EmittedToast) => {
      emitted.push(fields);
      return "quill-id";
    },
  },
}));

import { useErrorDetailsStore } from "@posthog/ui/features/notifications/errorDetailsStore";
import { toastOpenTaskError } from "@posthog/ui/features/tasks/toastOpenTaskError";

const RAW_404 =
  'Failed request: [404] {"type":"invalid_request","detail":"Not found."}';

// Everything the user can read: the toast itself, plus the payload the
// "View larger" action hands to the details dialog.
function surfacedText(): string {
  const last = emitted.at(-1);
  if (!last) throw new Error("no toast emitted");
  last.action?.onClick();
  const detail = useErrorDetailsStore.getState().detail;
  return JSON.stringify([last.title, last.description, detail?.error]);
}

describe("toastOpenTaskError", () => {
  beforeEach(() => {
    emitted.length = 0;
    useErrorDetailsStore.getState().close();
  });

  it("keeps a raw API payload out of the toast title", () => {
    toastOpenTaskError(new ApiRequestError(500, '{"detail":"Server error."}'));

    const toast = emitted.at(-1);
    expect(toast?.title).toBe("Failed to open task");
    expect(toast?.description).toContain("Failed request: [500]");
  });

  it.each([
    ["an error object", new ApiRequestError(404, '{"detail":"Not found."}')],
    ["a flattened message and status", RAW_404],
  ])("reports a 404 as not-yet-available, given %s", (_case, error) => {
    toastOpenTaskError(error, typeof error === "string" ? 404 : undefined);

    const toast = emitted.at(-1);
    expect(toast?.title).toBe("This task is not available yet");
    expect(toast?.description).toContain("Try again in a moment");
    // The details dialog must not fall back to the DRF body either.
    expect(surfacedText()).not.toContain("invalid_request");
  });
});
