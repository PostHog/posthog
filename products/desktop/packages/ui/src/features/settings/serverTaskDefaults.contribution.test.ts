import type { TaskDefaults } from "@posthog/api-client/posthog-client";
import type { HostTrpcClient } from "@posthog/host-router/client";
import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import type { FeatureFlags } from "@posthog/ui/features/feature-flags/identifiers";
import { registerRendererStateStorage } from "@posthog/ui/shell/rendererStorage";
import { describe, expect, it, vi } from "vitest";
import { ServerTaskDefaultsContribution } from "./serverTaskDefaults.contribution";
import { useSettingsStore } from "./settingsStore";

registerRendererStateStorage({
  getItem: vi.fn().mockResolvedValue(null),
  setItem: vi.fn().mockResolvedValue(undefined),
  removeItem: vi.fn().mockResolvedValue(undefined),
});

const getMyTaskRunConfig = vi.fn();
const setMyTaskDefaults = vi.fn().mockResolvedValue(undefined);

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  createAuthenticatedClient: () => ({ getMyTaskRunConfig, setMyTaskDefaults }),
}));

const flags = {
  isEnabled: () => true,
  onFlagsLoaded: () => () => {},
} as unknown as FeatureFlags;

const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

const openProject = (projectId: number) =>
  useAuthStore.setState({
    authState: {
      ...ANONYMOUS_AUTH_STATE,
      status: "authenticated",
      cloudRegion: "us",
      currentProjectId: projectId,
    },
  });

describe("ServerTaskDefaultsContribution", () => {
  it("does not carry a project's value into the next project when the person switches mid-sync", async () => {
    const inSync = { autoPublishCloudRuns: true, planModeOffered: true };
    useSettingsStore.setState({
      _hasHydrated: true,
      autoPublishCloudRuns: true,
      defaultInitialTaskMode: "plan",
      taskDefaultsOnServer: { "1": inSync, "2": inSync },
    });
    const projectOne = deferred<{ taskDefaults: TaskDefaults }>();
    getMyTaskRunConfig.mockImplementation((projectId: number) =>
      projectId === 1
        ? projectOne.promise
        : Promise.resolve({
            taskDefaults: {
              start_in_plan_mode: true,
              auto_publish_cloud_runs: true,
            },
          }),
    );
    openProject(1);

    new ServerTaskDefaultsContribution({} as HostTrpcClient, flags).start();
    openProject(2);
    await flush();
    // Project 1 was changed on web while its request ran.
    projectOne.resolve({
      taskDefaults: {
        start_in_plan_mode: true,
        auto_publish_cloud_runs: false,
      },
    });
    await flush();
    await flush();

    expect(useSettingsStore.getState().autoPublishCloudRuns).toBe(true);
    expect(setMyTaskDefaults).not.toHaveBeenCalledWith(2, expect.anything());
  });
});
