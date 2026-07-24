import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { SandboxCustomImage } from "@posthog/shared/domain-types";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const notifySpy = vi.fn();
vi.mock("@posthog/di/container", () => ({
  resolveServiceOptional: () => ({ notify: notifySpy }),
}));
vi.mock("@posthog/ui/features/notifications/notifications", () => ({
  NotificationBus: class {},
}));

import { watchImageBuild } from "./imageBuildWatcher";

const POLL_MS = 5000;

function clientReturning(images: Partial<SandboxCustomImage>[]): {
  client: PostHogAPIClient;
  list: ReturnType<typeof vi.fn>;
} {
  const list = vi.fn().mockResolvedValue(images);
  return {
    client: { listSandboxCustomImages: list } as unknown as PostHogAPIClient,
    list,
  };
}

describe("watchImageBuild", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    notifySpy.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("stops and notifies exactly once when the image reaches a terminal state", async () => {
    const onTerminal = vi.fn();
    const { client, list } = clientReturning([
      { id: "im-ready", status: "ready", name: "img", version: 1 },
    ]);

    watchImageBuild(client, "im-ready", onTerminal);
    await vi.advanceTimersByTimeAsync(POLL_MS);

    expect(onTerminal).toHaveBeenCalledTimes(1);
    expect(notifySpy).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    expect(list).toHaveBeenCalledTimes(1);
  });

  it("keeps polling while in progress without notifying", async () => {
    const { client, list } = clientReturning([
      { id: "im-building", status: "building", name: "img", version: 0 },
    ]);

    watchImageBuild(client, "im-building");
    await vi.advanceTimersByTimeAsync(POLL_MS * 3);

    expect(list).toHaveBeenCalledTimes(3);
    expect(notifySpy).not.toHaveBeenCalled();
  });

  it("ignores a second watcher for an already-watched image", async () => {
    const { client, list } = clientReturning([
      { id: "im-dup", status: "building", name: "img", version: 0 },
    ]);

    watchImageBuild(client, "im-dup");
    watchImageBuild(client, "im-dup");
    await vi.advanceTimersByTimeAsync(POLL_MS);

    expect(list).toHaveBeenCalledTimes(1);
  });

  it("stops after the consecutive-error limit and makes no further calls", async () => {
    const list = vi.fn().mockRejectedValue(new Error("boom"));
    const client = {
      listSandboxCustomImages: list,
    } as unknown as PostHogAPIClient;

    watchImageBuild(client, "im-err");
    await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    expect(list).toHaveBeenCalledTimes(3);

    await vi.advanceTimersByTimeAsync(POLL_MS * 3);
    expect(list).toHaveBeenCalledTimes(3);
  });
});
