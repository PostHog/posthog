import { stateStorage } from "@posthog/ui/shell/rendererStorage";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveStartupLocation } from "./startupLocation";

describe("startup location", () => {
  afterEach(() => vi.restoreAllMocks());

  it("restores the exact last location", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue("/code");
    const client = {
      getTaskChannels: vi.fn(),
    };

    await expect(resolveStartupLocation("project", client)).resolves.toBe(
      "/code",
    );
    expect(client.getTaskChannels).not.toHaveBeenCalled();
  });

  it("opens a new task in me when there is no saved location", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      getTaskChannels: vi.fn().mockResolvedValue([
        {
          id: "me-id",
          name: "me",
          channel_type: "personal",
          starred: false,
        },
      ]),
    };

    await expect(resolveStartupLocation("project", client)).resolves.toBe(
      "/website/me-id/new",
    );
    expect(client.getTaskChannels).toHaveBeenCalledOnce();
  });
});
