import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  readTaskDragData,
  TASK_DRAG_TYPE,
  TASK_IDS_DRAG_TYPE,
  taskIdsForDrag,
  writeTaskDragData,
} from "./taskDrag";
import { useTaskSelectionStore } from "./taskSelectionStore";

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
});
