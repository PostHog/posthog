import type {
  TaskData,
  TaskGroup,
} from "@posthog/core/sidebar/sidebarData.types";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  dragSiblingCandidates,
  readTaskDragData,
  TASK_DRAG_TYPE,
  TASK_IDS_DRAG_TYPE,
  taskIdsForDrag,
  writeTaskDragData,
} from "./taskDrag";
import { useTaskSelectionStore } from "./taskSelectionStore";

function task(id: string, isPinned = false): TaskData {
  return {
    id,
    title: id,
    createdAt: 0,
    lastActivityAt: 0,
    isGenerating: false,
    isUnread: false,
    isPinned,
    needsPermission: false,
    repository: null,
    isSuspended: false,
    folderPath: null,
    cloudPrUrl: null,
    branchName: null,
    linkedBranch: null,
  };
}

describe("task drag data", () => {
  beforeEach(() => {
    useTaskSelectionStore.setState({
      selectedTaskIds: [],
      lastClickedId: null,
    });
  });

  it("drags the full selection when the grabbed task is selected", () => {
    expect(taskIdsForDrag("b", ["a", "b", "c"])).toEqual(["b", "a", "c"]);
  });

  it("drags only the grabbed task when it is outside the selection", () => {
    expect(taskIdsForDrag("d", ["a", "b", "c"])).toEqual(["d"]);
  });

  it("writes the selection and reads it back in drag order", () => {
    useTaskSelectionStore.setState({ selectedTaskIds: ["a", "b"] });
    const payload = new Map<string, string>();
    const setData = vi.fn((type: string, value: string) => {
      payload.set(type, value);
    });

    writeTaskDragData({ setData }, "b");

    expect(setData).toHaveBeenCalledWith(TASK_DRAG_TYPE, "b");
    expect(setData).toHaveBeenCalledWith(
      TASK_IDS_DRAG_TYPE,
      JSON.stringify(["b", "a"]),
    );
    expect(
      readTaskDragData({ getData: (type) => payload.get(type) ?? "" }),
    ).toEqual(["b", "a"]);
  });

  // by-project caps each group on its own, so "c"/"d" render in the second
  // project yet fall outside the flat top window — resolving a batch there
  // against flatTasks would silently drop them.
  const lists = {
    pinnedTasks: [task("p", true)],
    flatTasks: [task("a"), task("b")],
    groupedTasks: [
      { id: "proj-1", name: "proj-1", tasks: [task("a"), task("b")] },
      { id: "proj-2", name: "proj-2", tasks: [task("c"), task("d")] },
    ] satisfies TaskGroup[],
  };

  it.each([
    ["by-project", ["p", "a", "b", "c", "d"]],
    ["chronological", ["p", "a", "b"]],
  ] as const)(
    "resolves batch-drag candidates against the %s rendered list",
    (mode, expectedIds) => {
      expect(dragSiblingCandidates(mode, lists).map((t) => t.id)).toEqual(
        expectedIds,
      );
    },
  );
});
