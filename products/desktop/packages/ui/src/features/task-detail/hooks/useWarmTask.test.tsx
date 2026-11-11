import {
  type WarmTaskClient,
  WarmTaskService,
} from "@posthog/core/task-detail/warmTaskService";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  enabled: true,
  scope: "us:1",
  user: "user-one",
}));
const client = vi.hoisted(() => ({
  warmTask: vi.fn<WarmTaskClient["warmTask"]>(),
  cancelTaskRun: vi.fn<WarmTaskClient["cancelTaskRun"]>(),
}));
let service: WarmTaskService;
vi.mock("@posthog/di/react", () => ({ useService: () => service }));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => client,
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => state.enabled,
}));
vi.mock("../../auth/store", () => ({
  getAuthIdentity: vi.fn(),
  useAuthStateValue: () => state.scope,
}));
vi.mock("../../auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { uuid: state.user } }),
}));

import { type UseWarmTaskOptions, useWarmTask } from "./useWarmTask";

const cloudTyping: UseWarmTaskOptions = {
  sessionId: "composer",
  workspaceMode: "cloud",
  selectedRepository: "example/project",
  githubIntegrationId: 1,
  editorIsEmpty: false,
};
const log = { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() };
async function flush(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(600);
  });
}

describe("useWarmTask", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    Object.assign(state, { enabled: true, scope: "us:1", user: "user-one" });
    service = new WarmTaskService({ ...log, scope: () => log });
    client.warmTask.mockResolvedValue({
      task_id: "warm-task",
      run_id: "warm-run",
    });
    client.cancelTaskRun.mockResolvedValue({});
  });
  afterEach(() => vi.useRealTimers());

  it.each<Partial<UseWarmTaskOptions>>([
    { workspaceMode: "local" },
    { editorIsEmpty: true },
    { selectedRepository: null },
    { githubIntegrationId: undefined },
    { agentRuntime: "pi" },
    { contextWindow: "1m" },
    { fastMode: true },
    { claudeModelAccess: "own-subscription" },
    { codexModelAccess: "own-subscription" },
  ])("does not speculate for an ineligible composer %j", async (selection) => {
    renderHook(() => useWarmTask({ ...cloudTyping, ...selection }));
    await flush();
    expect(client.warmTask).not.toHaveBeenCalled();
  });

  it("releases an abandoned warm and keeps its budget across remounts", async () => {
    const first = renderHook(() => useWarmTask(cloudTyping));
    await flush();
    first.unmount();
    await flush();
    renderHook(() => useWarmTask(cloudTyping));
    await flush();
    expect(client.warmTask).toHaveBeenCalledTimes(1);
    expect(client.cancelTaskRun).toHaveBeenCalledExactlyOnceWith(
      "warm-task",
      "warm-run",
      undefined,
      true,
    );
  });

  it.each(["scope", "user"] as const)(
    "isolates %s changes and releases the prior account's warm",
    async (field) => {
      const { rerender } = renderHook(() => useWarmTask(cloudTyping));
      await flush();
      state[field] = "different";
      rerender();
      await flush();
      expect(client.warmTask).toHaveBeenCalledTimes(2);
      expect(client.cancelTaskRun).toHaveBeenCalledTimes(1);
    },
  );

  it("warms repo-less channels with their actual selection", async () => {
    renderHook(() =>
      useWarmTask({
        ...cloudTyping,
        allowNoRepo: true,
        repositories: [],
        runtimeAdapter: "claude",
        permissionMode: "plan",
      }),
    );
    await flush();
    expect(client.warmTask).toHaveBeenCalledExactlyOnceWith({
      repository: null,
      repositories: [],
      github_integration: null,
      branch: null,
      runtime_adapter: "claude",
      model: null,
      reasoning_effort: null,
      initial_permission_mode: "plan",
    });
  });
});
