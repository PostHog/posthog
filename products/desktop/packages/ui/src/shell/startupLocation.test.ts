import { stateStorage } from "@posthog/ui/shell/rendererStorage";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveStartupLocation } from "./startupLocation";

describe("startup location", () => {
  afterEach(() => vi.restoreAllMocks());

  it("restores the exact last location", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue("/code");
    const client = {
      getTaskChannels: vi.fn(),
      provisionDefaultTaskChannels: vi.fn(),
    };

    await expect(resolveStartupLocation("project", client)).resolves.toEqual({
      href: "/code",
      firstRun: null,
    });
    expect(client.getTaskChannels).not.toHaveBeenCalled();
    expect(client.provisionDefaultTaskChannels).not.toHaveBeenCalled();
  });

  it("lands a first-run user on the general space home", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      provisionDefaultTaskChannels: vi.fn(),
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
    // Both default spaces already exist, so no provisioning round-trip.
    expect(client.provisionDefaultTaskChannels).not.toHaveBeenCalled();
  });

  it("provisions the default spaces when the list lacks them", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      getTaskChannels: vi.fn().mockResolvedValue([]),
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [
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
            starred: false,
            system_role: "general",
          },
        ],
        personal_created: true,
        general_created: true,
      }),
    };

    await expect(resolveStartupLocation("project", client)).resolves.toEqual({
      href: "/website/general-id",
      firstRun: { generalChannelId: "general-id" },
    });
    expect(client.provisionDefaultTaskChannels).toHaveBeenCalledOnce();
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
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [
          {
            id: "me-id",
            name: "me",
            channel_type: "personal",
            starred: false,
          },
        ],
        personal_created: false,
        general_created: false,
      }),
    };

    await expect(resolveStartupLocation("project", client)).resolves.toEqual({
      href: "/website/me-id/new",
      firstRun: null,
    });
    expect(client.getTaskChannels).toHaveBeenCalledOnce();
  });
});
