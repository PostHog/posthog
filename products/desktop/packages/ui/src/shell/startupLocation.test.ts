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

    await expect(resolveStartupLocation("project", client)).resolves.toEqual({
      href: "/code",
      firstRun: null,
    });
    expect(client.getTaskChannels).not.toHaveBeenCalled();
  });

  it("lands a first-run user on the general space home", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      getTaskChannels: vi.fn().mockResolvedValue([
        {
          id: "me-id",
          name: "me",
          channel_type: "personal",
          starred: false,
          system_role: "personal",
        },
        {
          id: "general-id",
          name: "general",
          channel_type: "public",
          starred: true,
          system_role: "general",
        },
      ]),
    };

    await expect(resolveStartupLocation("project", client)).resolves.toEqual({
      href: "/website/general-id",
      firstRun: { generalChannelId: "general-id" },
    });
    expect(client.getTaskChannels).toHaveBeenCalledOnce();
  });

  it("falls back to the personal channel when the server has no #general yet", async () => {
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

    await expect(resolveStartupLocation("project", client)).resolves.toEqual({
      href: "/website/me-id/new",
      firstRun: null,
    });
    expect(client.getTaskChannels).toHaveBeenCalledOnce();
  });
});
