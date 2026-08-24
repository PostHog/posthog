import { stateStorage } from "@posthog/ui/shell/rendererStorage";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  primeStartupProvision,
  resolveStartupLocation,
} from "./startupLocation";

const personal = {
  id: "me-id",
  name: "me",
  channel_type: "personal" as const,
  starred: false,
  created_at: "2026-01-01T00:00:00Z",
  system_role: "personal" as const,
};
const general = {
  id: "general-id",
  name: "general",
  channel_type: "public" as const,
  starred: false,
  created_at: "2026-01-01T00:00:00Z",
  system_role: "general" as const,
};

describe("startup location", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reopens a location saved before the routes were flattened", async () => {
    vi.spyOn(stateStorage, "getItem").mockImplementation(async (key) =>
      key.includes(":v2:") ? "/website/eng/loops" : null,
    );
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: false,
        general_created: false,
      }),
      startOnboardingSession: vi.fn(),
    };

    await expect(
      resolveStartupLocation("project", client, true),
    ).resolves.toEqual({ href: "/spaces/eng/loops", firstRun: null });
  });

  it("restores the exact last location", async () => {
    vi.spyOn(stateStorage, "getItem").mockImplementation(async (key) =>
      key.includes(":v2:") ? "/code" : null,
    );
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: false,
        general_created: false,
      }),
      startOnboardingSession: vi.fn(),
    };

    await expect(
      resolveStartupLocation("project", client, true),
    ).resolves.toEqual({
      href: "/code",
      firstRun: null,
    });
    expect(client.startOnboardingSession).not.toHaveBeenCalled();
  });

  it("lands a first-run user on the general space home", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: true,
        general_created: true,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };

    await expect(
      resolveStartupLocation("project", client, true),
    ).resolves.toEqual({
      href: "/spaces/general-id/tasks/session-id",
      firstRun: { generalChannelId: "general-id" },
    });
  });

  it("does not open a second session when the spaces already existed", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: false,
        general_created: true,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };

    await resolveStartupLocation("project", client, true);

    expect(client.startOnboardingSession).not.toHaveBeenCalled();
  });

  it("opens the app even when starting the session never resolves", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: true,
        general_created: true,
      }),
      startOnboardingSession: vi.fn().mockReturnValue(new Promise(() => {})),
    };

    vi.useFakeTimers();
    const resolving = resolveStartupLocation("project", client, true);
    await vi.runAllTimersAsync();
    vi.useRealTimers();

    await expect(resolving).resolves.toEqual({
      href: "/spaces/general-id",
      firstRun: { generalChannelId: "general-id" },
    });
    expect(client.startOnboardingSession).toHaveBeenCalled();
  });

  it("skips the first-run treatment when the server created nothing", async () => {
    // A reinstall loses the saved location while the spaces survive.
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: false,
        general_created: false,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };

    await expect(
      resolveStartupLocation("project", client, true),
    ).resolves.toEqual({
      href: "/spaces/general-id",
      firstRun: null,
    });
  });

  it("carries an install from before provisioning back to where it was", async () => {
    // The old key is the only trace of an install that predates the default
    // spaces, and it still has to land where the user left off.
    vi.spyOn(stateStorage, "getItem").mockImplementation(async (key) =>
      key.includes(":v2:") ? null : "/spaces/old-space",
    );
    const removeItem = vi
      .spyOn(stateStorage, "removeItem")
      .mockResolvedValue(undefined);
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: true,
        general_created: true,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };

    await expect(
      resolveStartupLocation("project", client, true),
    ).resolves.toEqual({
      href: "/spaces/old-space",
      firstRun: null,
    });
    expect(client.provisionDefaultTaskChannels).toHaveBeenCalledOnce();
    expect(removeItem).toHaveBeenCalledWith("startup-location:project");
  });

  it("opens anyway when provisioning is unavailable", async () => {
    // A server that cannot provision yet must not cost someone their location.
    vi.spyOn(stateStorage, "getItem").mockImplementation(async (key) =>
      key.includes(":v2:") ? null : "/spaces/old-space",
    );
    const removeItem = vi
      .spyOn(stateStorage, "removeItem")
      .mockResolvedValue(undefined);
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockRejectedValue(new Error("404")),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };

    await expect(
      resolveStartupLocation("project", client, true),
    ).resolves.toEqual({
      href: "/spaces/old-space",
      firstRun: null,
    });
    expect(removeItem).not.toHaveBeenCalled();
  });

  it("ignores a hand-off primed by a different account", async () => {
    // A logout or account switch between priming and consuming would otherwise hand the
    // next account the previous project's channels.
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: false,
        general_created: false,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };
    primeStartupProvision(
      "someone-else",
      Promise.resolve({
        channels: [personal, general],
        personal_created: true,
        general_created: true,
      }),
    );

    await expect(
      resolveStartupLocation("project", client, true),
    ).resolves.toEqual({ href: "/spaces/general-id", firstRun: null });
    expect(client.provisionDefaultTaskChannels).toHaveBeenCalledOnce();
  });

  it("keeps a spaces-off user on a route they can navigate away from", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: true,
        general_created: true,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };

    await expect(
      resolveStartupLocation("project", client, false),
    ).resolves.toEqual({ href: "/code", firstRun: null });
  });

  it("takes the first run over a saved location when onboarding just provisioned", async () => {
    vi.spyOn(stateStorage, "getItem").mockImplementation(async (key) =>
      key.includes(":v2:") ? "/settings" : null,
    );
    const client = {
      provisionDefaultTaskChannels: vi.fn(),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };
    primeStartupProvision(
      "project",
      Promise.resolve({
        channels: [personal, general],
        personal_created: true,
        general_created: false,
      }),
    );

    await expect(
      resolveStartupLocation("project", client, true),
    ).resolves.toEqual({
      href: "/spaces/general-id/tasks/session-id",
      firstRun: { generalChannelId: "general-id" },
    });
  });

  it("consumes a primed provisioning result exactly once", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      provisionDefaultTaskChannels: vi.fn(),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };
    primeStartupProvision(
      "project",
      Promise.resolve({
        channels: [personal, general],
        personal_created: true,
        general_created: false,
      }),
    );

    await expect(
      resolveStartupLocation("project", client, true),
    ).resolves.toEqual({
      href: "/spaces/general-id/tasks/session-id",
      firstRun: { generalChannelId: "general-id" },
    });
    expect(client.provisionDefaultTaskChannels).not.toHaveBeenCalled();

    const again = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: false,
        general_created: false,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };
    await resolveStartupLocation("project", again, true);
    expect(again.provisionDefaultTaskChannels).toHaveBeenCalledOnce();
  });
});
