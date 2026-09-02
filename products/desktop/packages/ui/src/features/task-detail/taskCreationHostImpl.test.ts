import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/di/container", () => ({
  resolveService: vi.fn(),
}));

vi.mock("../../shell/analytics", () => ({
  track: vi.fn(),
  captureException: vi.fn(),
}));

import { TrpcTaskCreationHost } from "./taskCreationHostImpl";

const args = {
  repoPath: "/repo",
  environmentId: "env-1",
  name: "Dev",
  script: "npm run setup",
};

describe("TrpcTaskCreationHost.confirmEnvironmentSetup", () => {
  const host = new TrpcTaskCreationHost();

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each([
    { answer: true, expected: true },
    { answer: false, expected: false },
  ])(
    "returns $expected when the user answers $answer",
    async ({ answer, expected }) => {
      vi.spyOn(window, "confirm").mockReturnValue(answer);

      await expect(host.confirmEnvironmentSetup(args)).resolves.toBe(expected);
    },
  );

  it("prompts on every run so an earlier answer cannot be reused", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    await host.confirmEnvironmentSetup(args);
    await host.confirmEnvironmentSetup(args);

    expect(confirmSpy).toHaveBeenCalledTimes(2);
  });

  it("warns that the script can execute other files in the repository", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    await host.confirmEnvironmentSetup(args);

    expect(confirmSpy.mock.calls[0][0]).toContain(
      "can execute other files in the repository",
    );
  });
});
