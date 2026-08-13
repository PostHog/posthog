import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTaskSelectionStore } from "./taskSelectionStore";
import { useSidebarBulkActions } from "./useSidebarBulkActions";

const hoisted = vi.hoisted(() => ({
  archiveTasksImperative: vi.fn(),
  setPinnedMany: vi.fn(),
  placeTasksInCommandCenter: vi.fn(),
  fileTask: vi.fn(),
  useChannels: vi.fn(),
  useFeatureFlag: vi.fn(),
  useTasks: vi.fn(),
  pinnedTaskIds: new Set<string>(),
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock("@posthog/ui/features/archive/useArchiveTask", () => ({
  archiveTasksImperative: hoisted.archiveTasksImperative,
  useArchiveCacheKeys: () => ({}),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: hoisted.useChannels,
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelTasks", () => ({
  useChannelTaskMutations: () => ({ fileTask: hoisted.fileTask }),
}));

vi.mock("@posthog/ui/features/command-center/placeTaskInCommandCenter", () => ({
  placeTasksInCommandCenter: hoisted.placeTasksInCommandCenter,
}));

vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: hoisted.useFeatureFlag,
}));

vi.mock("./usePinnedTasks", () => ({
  usePinnedTasks: () => ({
    pinnedTaskIds: hoisted.pinnedTaskIds,
    setPinnedMany: hoisted.setPinnedMany,
    isSettingPinnedMany: false,
  }),
}));

vi.mock("@posthog/ui/features/tasks/useTasks", () => ({
  useTasks: hoisted.useTasks,
}));

vi.mock("@posthog/ui/primitives/toast", () => ({ toast: hoisted.toast }));

vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({}) }));

function makeTask(id: string, overrides: Partial<TaskData> = {}): TaskData {
  return {
    id,
    title: id,
    createdAt: 0,
    lastActivityAt: 0,
    isGenerating: false,
    isUnread: false,
    isPinned: false,
    needsPermission: false,
    repository: null,
    isSuspended: false,
    folderPath: null,
    cloudPrUrl: null,
    branchName: null,
    linkedBranch: null,
    ...overrides,
  } as TaskData;
}

const TASKS = [makeTask("t1"), makeTask("t2")];

function render(taskIds: string[] = ["t1", "t2"]) {
  return renderHook(() => useSidebarBulkActions(taskIds, TASKS));
}

describe("useSidebarBulkActions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.pinnedTaskIds = new Set();
    hoisted.useChannels.mockReturnValue({
      channels: [{ id: "c1", name: "support" }],
      isLoading: false,
    });
    hoisted.useFeatureFlag.mockReturnValue(true);
    hoisted.useTasks.mockReturnValue({ data: [{ id: "t1" }, { id: "t2" }] });
    hoisted.setPinnedMany.mockResolvedValue({
      succeeded: ["t1", "t2"],
      failed: [],
    });
    hoisted.archiveTasksImperative.mockResolvedValue({
      archived: 2,
      failed: 0,
    });
    hoisted.placeTasksInCommandCenter.mockReturnValue({
      placed: 2,
      overflow: 0,
      alreadyPresent: 0,
    });
    hoisted.fileTask.mockReset();
    hoisted.fileTask.mockResolvedValue(undefined);
    useTaskSelectionStore.setState({
      selectedTaskIds: ["t1", "t2"],
      lastClickedId: null,
    });
  });

  it.each([
    {
      name: "none pinned",
      pinned: [],
      direction: "pin",
      label: "Pin 2 sessions",
    },
    {
      name: "some pinned",
      pinned: ["t1"],
      direction: "pin",
      label: "Pin 2 sessions",
    },
    {
      name: "all pinned",
      pinned: ["t1", "t2"],
      direction: "unpin",
      label: "Unpin 2 sessions",
    },
  ])(
    "labels the pin action $direction when $name",
    ({ pinned, direction, label }) => {
      hoisted.pinnedTaskIds = new Set(pinned);

      const { result } = render();

      expect(result.current.pinDirection).toBe(direction);
      expect(result.current.pinLabel).toBe(label);
    },
  );

  it("pins the whole selection in the computed direction", async () => {
    hoisted.pinnedTaskIds = new Set(["t1", "t2"]);
    const { result } = render();

    await act(() => result.current.pinSelected());

    expect(hoisted.setPinnedMany).toHaveBeenCalledWith(["t1", "t2"], false);
  });

  it("clears the selection when every session succeeded", async () => {
    const { result } = render();

    await act(() => result.current.pinSelected());

    await waitFor(() =>
      expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([]),
    );
  });

  // Keeping the failures selected is what lets the user retry just those.
  it("keeps only the failures selected after a partial failure", async () => {
    hoisted.setPinnedMany.mockResolvedValue({
      succeeded: ["t1"],
      failed: ["t2"],
    });
    const { result } = render();

    await act(() => result.current.pinSelected());

    await waitFor(() =>
      expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual(["t2"]),
    );
  });

  describe("addSelectedToCommandCenter", () => {
    it("reports how many landed on the grid", () => {
      const { result } = render();

      act(() => result.current.addSelectedToCommandCenter());

      expect(hoisted.toast.success).toHaveBeenCalledWith(
        "2 sessions added to Command Center",
      );
    });

    // "0 sessions added" reads as a failure when the grid is exactly as asked.
    it("says the batch was already there rather than reporting zero added", () => {
      hoisted.placeTasksInCommandCenter.mockReturnValue({
        placed: 0,
        overflow: 0,
        alreadyPresent: 2,
      });
      const { result } = render();

      act(() => result.current.addSelectedToCommandCenter());

      expect(hoisted.toast.success).not.toHaveBeenCalled();
      expect(hoisted.toast.info).toHaveBeenCalledWith(
        "2 sessions already in Command Center",
      );
    });

    // The selection survives so the leftovers can go somewhere in one click,
    // matching what archive and file do with the sessions they couldn't take.
    it("warns about sessions that didn't fit and keeps the selection", () => {
      hoisted.placeTasksInCommandCenter.mockReturnValue({
        placed: 1,
        overflow: 1,
        alreadyPresent: 0,
      });
      const { result } = render();

      act(() => result.current.addSelectedToCommandCenter());

      expect(hoisted.toast.warning).toHaveBeenCalledWith(
        "1 added to Command Center, 1 didn't fit",
      );
      expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([
        "t1",
        "t2",
      ]);
    });

    // A cell holding a deleted task draws empty, so placement needs the live
    // list to see the same free tile — and null, not an empty set, while that
    // list is still loading, or it would tile over sessions already on the grid.
    it.each([
      {
        name: "the loaded task ids",
        data: [{ id: "t9" }],
        live: new Set(["t9"]),
      },
      { name: "null before the list loads", data: undefined, live: null },
    ])("places against $name", ({ data, live }) => {
      hoisted.useTasks.mockReturnValue({ data });
      const { result } = render();

      act(() => result.current.addSelectedToCommandCenter());

      expect(hoisted.placeTasksInCommandCenter).toHaveBeenCalledWith(
        ["t1", "t2"],
        live,
      );
    });
  });

  // stopsCloudSandbox drives the warning's "Any cloud sandbox … shuts down
  // too", so it has to track the environment rather than just "running".
  it.each([
    { environment: "cloud", stopsCloudSandbox: true },
    { environment: "local", stopsCloudSandbox: false },
  ] as const)(
    "counts a running $environment session and reports stopsCloudSandbox=$stopsCloudSandbox",
    ({ environment, stopsCloudSandbox }) => {
      const tasks = [
        makeTask("t1", { isGenerating: true, taskRunEnvironment: environment }),
        makeTask("t2"),
      ];

      const { result } = renderHook(() =>
        useSidebarBulkActions(["t1", "t2"], tasks),
      );

      expect(result.current.runningCount).toBe(1);
      expect(result.current.stopsCloudSandbox).toBe(stopsCloudSandbox);
    },
  );

  describe("archiveSelected", () => {
    it("clears the selection when every session was archived", async () => {
      const { result } = render();

      await act(() => result.current.archiveSelected());

      expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([]);
      expect(hoisted.toast.success).toHaveBeenCalledWith("2 sessions archived");
    });

    // Deliberately unlike pinSelected, which narrows to the failures: archiving
    // reports counts rather than ids, so there is nothing to narrow to and the
    // whole selection stays put for a retry.
    it("keeps the whole selection after a partial failure", async () => {
      hoisted.archiveTasksImperative.mockResolvedValue({
        archived: 1,
        failed: 1,
      });
      const { result } = render();

      await act(() => result.current.archiveSelected());

      expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([
        "t1",
        "t2",
      ]);
      expect(hoisted.toast.error).toHaveBeenCalledWith("1 archived, 1 failed");
    });

    it("reports a thrown archive rather than rejecting", async () => {
      hoisted.archiveTasksImperative.mockRejectedValue(new Error("network"));
      const { result } = render();

      await act(() => result.current.archiveSelected());

      expect(hoisted.toast.error).toHaveBeenCalledWith(
        "Couldn't archive the selected sessions",
      );
      expect(result.current.isArchiving).toBe(false);
    });
  });

  it("files every selected session to the chosen channel", async () => {
    const { result } = render();

    await act(() => result.current.fileSelectedTo("c1"));

    expect(hoisted.fileTask.mock.calls).toEqual([
      ["c1", "t1"],
      ["c1", "t2"],
    ]);
  });

  // Narrowing to the failures is what makes a retry one click.
  it("keeps only the sessions that failed to file selected", async () => {
    hoisted.fileTask.mockImplementation((_channelId: string, taskId: string) =>
      taskId === "t2" ? Promise.reject(new Error("nope")) : Promise.resolve(),
    );
    const { result } = render();

    await act(() => result.current.fileSelectedTo("c1"));

    await waitFor(() =>
      expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual(["t2"]),
    );
    expect(hoisted.toast.error).toHaveBeenCalledWith("1 filed, 1 failed");
  });

  // `enabled: false` stops the fetch but still hands back whatever an ungated
  // surface already put in the shared cache, so the flag has to gate the list.
  it("offers no channels when the bluebird flag is off", () => {
    hoisted.useFeatureFlag.mockReturnValue(false);
    hoisted.useChannels.mockReturnValue({
      channels: [{ id: "c1", name: "support" }],
      isLoading: false,
    });

    const { result } = render();

    expect(result.current.channels).toEqual([]);
    expect(result.current.fileDisabledReason).not.toBeNull();
    expect(hoisted.useChannels).toHaveBeenCalledWith({ enabled: false });
  });

  it.each([
    { action: "archiveDisabledReason" },
    { action: "pinDisabledReason" },
    { action: "commandCenterDisabledReason" },
    { action: "fileDisabledReason" },
  ] as const)("disables $action with nothing selected", ({ action }) => {
    const { result } = render([]);

    expect(result.current[action]).not.toBeNull();
  });
});
