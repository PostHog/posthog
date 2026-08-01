import { stateStorage } from "@posthog/ui/shell/rendererStorage";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveStartupLocation } from "./startupLocation";

describe("startup location", () => {
  afterEach(() => vi.restoreAllMocks());

  it("restores the exact last location", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue("/code");
    const client = {
      getDesktopFileSystemChannels: vi.fn(),
      createDesktopFileSystemChannel: vi.fn(),
    };

    await expect(resolveStartupLocation("project", client)).resolves.toBe(
      "/code",
    );
    expect(client.getDesktopFileSystemChannels).not.toHaveBeenCalled();
  });

  it("opens a new task in me when there is no saved location", async () => {
    vi.spyOn(stateStorage, "getItem").mockResolvedValue(null);
    const client = {
      getDesktopFileSystemChannels: vi
        .fn()
        .mockResolvedValue([{ id: "me-id", path: "me", type: "folder" }]),
      createDesktopFileSystemChannel: vi.fn(),
    };

    await expect(resolveStartupLocation("project", client)).resolves.toBe(
      "/website/me-id/new",
    );
    expect(client.createDesktopFileSystemChannel).not.toHaveBeenCalled();
  });
});
