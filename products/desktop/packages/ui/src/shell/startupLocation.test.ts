import { rewriteSavedLocation } from "@posthog/shared";
import type { ProvisionedTaskChannels } from "@posthog/shared/domain-types";
import { stateStorage } from "@posthog/ui/shell/rendererStorage";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { beginFirstRun, ensureSession, firstRun } from "./firstRun";
import { resolveStartupLocation } from "./startupLocation";

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

// Each case gets its own identity so the module-level first run from a previous one is never
// the thing under test.
let identityCounter = 0;
let identity = "project";

describe("rewriteSavedLocation", () => {
  // A saved location is a raw href, so an install that last quit before the
  // routes were flattened would otherwise reopen on a route that is gone.
  it.each([
    ["/website", "/spaces"],
    ["/website/eng", "/spaces/eng"],
    ["/website/eng/loops", "/spaces/eng/loops"],
    ["/website/home", "/"],
    ["/website/activity", "/activity"],
    ["/website/activity?taskId=task-1", "/activity?taskId=task-1"],
    ["/website/home#recent", "/#recent"],
    ["/website/command-center", "/command-center"],
    ["/website/new", "/new"],
    ["/code", "/new"],
    ["/code/inbox/pulls/42", "/inbox/pulls/42"],
    ["/code/inbox?filter=mine", "/inbox?filter=mine"],
    ["/code/loops/abc/edit", "/loops/abc/edit"],
    ["/code/tasks/t1", "/tasks/t1"],
  ])("moves %s to %s", (saved, expected) => {
    expect(rewriteSavedLocation(saved)).toBe(expected);
  });

  it.each(["/spaces/eng", "/inbox", "/settings/general", "/"])(
    "leaves %s alone",
    (href) => {
      expect(rewriteSavedLocation(href)).toBe(href);
    },
  );
});

describe("startup location", () => {
  beforeEach(() => {
    identityCounter += 1;
    identity = `project-${identityCounter}`;
  });
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
      resolveStartupLocation(identity, client, true),
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
      resolveStartupLocation(identity, client, true),
    ).resolves.toEqual({
      href: "/new",
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
      resolveStartupLocation(identity, client, true),
    ).resolves.toEqual({
      href: "/spaces/general-id/tasks/session-id",
      firstRun: { generalChannelId: "general-id" },
    });
  });

  it("opens the session when only #general is new", async () => {
    // Creating a task ensures the personal space, so someone who reached the composer before
    // provisioning ran owns a personal space it did not create. Only #general proves a first run.
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: false,
        general_created: true,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };

    await expect(
      resolveStartupLocation(identity, client, true),
    ).resolves.toEqual({
      href: "/spaces/general-id/tasks/session-id",
      firstRun: { generalChannelId: "general-id" },
    });
  });

  it("does not open a second session when both spaces already existed", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: false,
        general_created: false,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };

    await resolveStartupLocation(identity, client, true);

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
    const resolving = resolveStartupLocation(identity, client, true);
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
      resolveStartupLocation(identity, client, true),
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
      resolveStartupLocation(identity, client, true),
    ).resolves.toEqual({
      href: "/spaces/old-space",
      firstRun: null,
    });
    expect(client.provisionDefaultTaskChannels).toHaveBeenCalledOnce();
    expect(removeItem).toHaveBeenCalledWith(`startup-location:${identity}`);
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
      resolveStartupLocation(identity, client, true),
    ).resolves.toEqual({
      href: "/spaces/old-space",
      firstRun: null,
    });
    expect(removeItem).not.toHaveBeenCalled();
  });

  it("falls back to code when provisioning and saved locations are unavailable", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockRejectedValue(new Error("503")),
      startOnboardingSession: vi.fn(),
    };

    await expect(
      resolveStartupLocation(identity, client, true),
    ).resolves.toEqual({ href: "/code", firstRun: null });
    expect(client.startOnboardingSession).not.toHaveBeenCalled();
  });

  it("ignores a first run started by a different account", async () => {
    // A logout or account switch between starting and reading would otherwise hand the
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
    beginFirstRun("someone-else", {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: true,
        general_created: true,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("other-session"),
    });

    await expect(
      resolveStartupLocation(identity, client, true),
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
      resolveStartupLocation(identity, client, false),
    ).resolves.toEqual({ href: "/code", firstRun: null });
  });

  it("takes the first run over a saved location when onboarding just provisioned", async () => {
    vi.spyOn(stateStorage, "getItem").mockImplementation(async (key) =>
      key.includes(":v2:") ? "/settings" : null,
    );
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: true,
        general_created: false,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };
    beginFirstRun(identity, client);

    await expect(
      resolveStartupLocation(identity, client, true),
    ).resolves.toEqual({
      href: "/spaces/general-id/tasks/session-id",
      firstRun: { generalChannelId: "general-id" },
    });
  });

  it("shares one provisioning result between onboarding and startup", async () => {
    // personal_created and general_created are true only for whoever provisions first, so a
    // second call here would report that this is not a first run.
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: true,
        general_created: false,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };

    beginFirstRun(identity, client);
    beginFirstRun(identity, client);

    await expect(
      resolveStartupLocation(identity, client, true),
    ).resolves.toEqual({
      href: "/spaces/general-id/tasks/session-id",
      firstRun: { generalChannelId: "general-id" },
    });
    expect(client.provisionDefaultTaskChannels).toHaveBeenCalledOnce();
    expect(client.startOnboardingSession).toHaveBeenCalledOnce();
  });

  it("shares one session between consent prefetch and startup", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    let finishProvisioning!: (value: ProvisionedTaskChannels) => void;
    const provisioned = new Promise<ProvisionedTaskChannels>((resolve) => {
      finishProvisioning = resolve;
    });
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockReturnValue(provisioned),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };

    beginFirstRun(identity, client);
    const prefetchedSession = ensureSession(identity, client);
    const startup = resolveStartupLocation(identity, client, true);

    expect(client.startOnboardingSession).not.toHaveBeenCalled();
    finishProvisioning({
      channels: [personal, general],
      personal_created: true,
      general_created: false,
    });

    await expect(prefetchedSession).resolves.toBe("session-id");
    await expect(startup).resolves.toEqual({
      href: "/spaces/general-id/tasks/session-id",
      firstRun: { generalChannelId: "general-id" },
    });
    expect(client.startOnboardingSession).toHaveBeenCalledOnce();
  });

  it("provisions again when an earlier attempt failed", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const failed = firstRun(identity, {
      provisionDefaultTaskChannels: vi.fn().mockRejectedValue(new Error("503")),
      startOnboardingSession: vi.fn(),
    });
    await expect(failed.provisioned).resolves.toBeNull();
    const client = {
      provisionDefaultTaskChannels: vi.fn().mockResolvedValue({
        channels: [personal, general],
        personal_created: true,
        general_created: false,
      }),
      startOnboardingSession: vi.fn().mockResolvedValue("session-id"),
    };

    await expect(
      resolveStartupLocation(identity, client, true),
    ).resolves.toEqual({
      href: "/spaces/general-id/tasks/session-id",
      firstRun: { generalChannelId: "general-id" },
    });
  });
});
