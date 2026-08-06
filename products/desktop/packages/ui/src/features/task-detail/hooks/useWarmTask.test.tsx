import type { WorkspaceMode } from "@posthog/shared";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  warmTask: vi.fn(),
}));
const flagState = vi.hoisted(() => ({ enabled: true }));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => flagState.enabled,
}));
vi.mock("../../../shell/logger", () => ({
  logger: { scope: () => ({ warn: vi.fn(), error: vi.fn() }) },
}));

import { useWarmTask } from "./useWarmTask";
import { takeWarmTaskLease } from "./warmTaskLease";

interface Props {
  workspaceMode: WorkspaceMode;
  selectedRepository?: string | null;
  githubIntegrationId?: number;
  branch?: string | null;
  editorIsEmpty: boolean;
  runtimeAdapter?: string | null;
  model?: string | null;
  reasoningEffort?: string | null;
  sandboxEnvironmentId?: string | null;
  customImageId?: string | null;
}

const cloudTyping: Props = {
  workspaceMode: "cloud",
  selectedRepository: "acme/repo",
  githubIntegrationId: 42,
  branch: "main",
  editorIsEmpty: false,
};

const NULL_RUNTIME = {
  runtime_adapter: null,
  model: null,
  reasoning_effort: null,
};

describe("useWarmTask", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    flagState.enabled = true;
    mockClient.warmTask.mockResolvedValue({
      task_id: "task-1",
      run_id: "run-1",
    });
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  async function flushDebounce(): Promise<void> {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
  }

  it("fires a debounced warm when cloud + repo + typing", async () => {
    renderHook((props: Props) => useWarmTask(props), {
      initialProps: cloudTyping,
    });

    expect(mockClient.warmTask).not.toHaveBeenCalled();

    await flushDebounce();

    expect(mockClient.warmTask).toHaveBeenCalledWith({
      repository: "acme/repo",
      github_integration: 42,
      branch: "main",
      ...NULL_RUNTIME,
    });
  });

  it.each<{ name: string; props?: Partial<Props>; flagEnabled?: boolean }>([
    { name: "the flag is off", flagEnabled: false },
    { name: "not in cloud mode", props: { workspaceMode: "local" } },
    { name: "no repository is selected", props: { selectedRepository: null } },
    {
      name: "no github integration",
      props: { githubIntegrationId: undefined },
    },
    { name: "the editor is empty", props: { editorIsEmpty: true } },
  ])("does not fire when $name", async ({ props, flagEnabled }) => {
    if (flagEnabled === false) {
      flagState.enabled = false;
    }
    renderHook((p: Props) => useWarmTask(p), {
      initialProps: { ...cloudTyping, ...props },
    });
    await flushDebounce();
    expect(mockClient.warmTask).not.toHaveBeenCalled();
  });

  it("fires once the editor becomes non-empty", async () => {
    const { rerender } = renderHook((props: Props) => useWarmTask(props), {
      initialProps: { ...cloudTyping, editorIsEmpty: true },
    });
    await flushDebounce();
    expect(mockClient.warmTask).not.toHaveBeenCalled();

    rerender(cloudTyping);
    await flushDebounce();
    expect(mockClient.warmTask).toHaveBeenCalledOnce();
  });

  it("does not re-fire for the same selection (backend dedups, client guards)", async () => {
    const { rerender } = renderHook((props: Props) => useWarmTask(props), {
      initialProps: cloudTyping,
    });
    await flushDebounce();
    expect(mockClient.warmTask).toHaveBeenCalledOnce();

    rerender({ ...cloudTyping });
    await flushDebounce();
    expect(mockClient.warmTask).toHaveBeenCalledOnce();
  });

  it("warms the new selection when the repository changes (no release)", async () => {
    const { rerender } = renderHook((props: Props) => useWarmTask(props), {
      initialProps: cloudTyping,
    });
    await flushDebounce();
    expect(mockClient.warmTask).toHaveBeenCalledOnce();

    rerender({ ...cloudTyping, selectedRepository: "acme/other" });
    await flushDebounce();

    expect(mockClient.warmTask).toHaveBeenLastCalledWith({
      repository: "acme/other",
      github_integration: 42,
      branch: "main",
      ...NULL_RUNTIME,
    });
    expect(mockClient.warmTask).toHaveBeenCalledTimes(2);
  });

  it("warms the new selection when the branch changes (no release)", async () => {
    const { rerender } = renderHook((props: Props) => useWarmTask(props), {
      initialProps: cloudTyping,
    });
    await flushDebounce();

    rerender({ ...cloudTyping, branch: "feature/x" });
    await flushDebounce();

    expect(mockClient.warmTask).toHaveBeenLastCalledWith({
      repository: "acme/repo",
      github_integration: 42,
      branch: "feature/x",
      ...NULL_RUNTIME,
    });
    expect(mockClient.warmTask).toHaveBeenCalledTimes(2);
  });

  it("forwards the selected runtime and re-warms when it changes", async () => {
    const { rerender } = renderHook((props: Props) => useWarmTask(props), {
      initialProps: {
        ...cloudTyping,
        runtimeAdapter: "claude",
        model: "claude-opus-4-8",
        reasoningEffort: "high",
      },
    });
    await flushDebounce();
    expect(mockClient.warmTask).toHaveBeenLastCalledWith({
      repository: "acme/repo",
      github_integration: 42,
      branch: "main",
      runtime_adapter: "claude",
      model: "claude-opus-4-8",
      reasoning_effort: "high",
    });

    rerender({
      ...cloudTyping,
      runtimeAdapter: "codex",
      model: "gpt-5.5",
      reasoningEffort: "high",
    });
    await flushDebounce();
    expect(mockClient.warmTask).toHaveBeenLastCalledWith({
      repository: "acme/repo",
      github_integration: 42,
      branch: "main",
      runtime_adapter: "codex",
      model: "gpt-5.5",
      reasoning_effort: "high",
    });
    expect(mockClient.warmTask).toHaveBeenCalledTimes(2);
  });

  it("forwards sandbox configuration and re-warms when the image changes", async () => {
    const { rerender } = renderHook((props: Props) => useWarmTask(props), {
      initialProps: {
        ...cloudTyping,
        sandboxEnvironmentId: "environment-123",
        customImageId: "image-123",
      },
    });
    await flushDebounce();
    expect(mockClient.warmTask).toHaveBeenLastCalledWith({
      repository: "acme/repo",
      github_integration: 42,
      branch: "main",
      ...NULL_RUNTIME,
      sandbox_environment_id: "environment-123",
      custom_image_id: "image-123",
    });

    rerender({
      ...cloudTyping,
      sandboxEnvironmentId: "environment-123",
      customImageId: "image-456",
    });
    await flushDebounce();
    expect(mockClient.warmTask).toHaveBeenLastCalledWith({
      repository: "acme/repo",
      github_integration: 42,
      branch: "main",
      ...NULL_RUNTIME,
      sandbox_environment_id: "environment-123",
      custom_image_id: "image-456",
    });
    expect(mockClient.warmTask).toHaveBeenCalledTimes(2);
  });

  it("warms only the latest image when selection changes during the debounce", async () => {
    const { rerender } = renderHook((props: Props) => useWarmTask(props), {
      initialProps: { ...cloudTyping, customImageId: "image-123" },
    });

    rerender({ ...cloudTyping, customImageId: "image-456" });
    await flushDebounce();

    expect(mockClient.warmTask).toHaveBeenCalledOnce();
    expect(mockClient.warmTask).toHaveBeenCalledWith({
      repository: "acme/repo",
      github_integration: 42,
      branch: "main",
      ...NULL_RUNTIME,
      custom_image_id: "image-456",
    });
  });

  it("keeps the latest image lease when warm responses complete out of order", async () => {
    type WarmResponse = { task_id: string; run_id: string };
    let resolveFirstWarm!: (value: WarmResponse) => void;
    let resolveSecondWarm!: (value: WarmResponse) => void;
    const firstWarm = new Promise<WarmResponse>((resolve) => {
      resolveFirstWarm = resolve;
    });
    const secondWarm = new Promise<WarmResponse>((resolve) => {
      resolveSecondWarm = resolve;
    });
    mockClient.warmTask
      .mockReturnValueOnce(firstWarm)
      .mockReturnValueOnce(secondWarm);

    const { rerender } = renderHook((props: Props) => useWarmTask(props), {
      initialProps: { ...cloudTyping, customImageId: "image-123" },
    });
    await flushDebounce();

    rerender({ ...cloudTyping, customImageId: "image-456" });
    await flushDebounce();

    await act(async () => {
      resolveSecondWarm({ task_id: "task-2", run_id: "run-2" });
      await secondWarm;
    });
    await act(async () => {
      resolveFirstWarm({ task_id: "task-1", run_id: "run-1" });
      await firstWarm;
    });

    expect(
      takeWarmTaskLease({
        repository: "acme/repo",
        branch: "main",
        runtimeAdapter: null,
        model: null,
        reasoningEffort: null,
        sandboxEnvironmentId: null,
        customImageId: "image-456",
      }),
    ).toEqual({ taskId: "task-2", runId: "run-2" });
  });

  it("warms again for a new selection after a failed warm", async () => {
    mockClient.warmTask.mockRejectedValueOnce(new Error("boom"));
    const { rerender } = renderHook((props: Props) => useWarmTask(props), {
      initialProps: cloudTyping,
    });
    await flushDebounce();
    expect(mockClient.warmTask).toHaveBeenCalledOnce();

    rerender({ ...cloudTyping, branch: "feature/x" });
    await flushDebounce();
    expect(mockClient.warmTask).toHaveBeenCalledTimes(2);
  });

  it("swallows warm errors without throwing", async () => {
    mockClient.warmTask.mockRejectedValue(new Error("boom"));
    renderHook((props: Props) => useWarmTask(props), {
      initialProps: cloudTyping,
    });

    await expect(flushDebounce()).resolves.not.toThrow();
    expect(mockClient.warmTask).toHaveBeenCalledOnce();
  });
});
