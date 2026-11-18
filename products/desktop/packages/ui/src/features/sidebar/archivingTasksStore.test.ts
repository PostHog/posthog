import { beforeEach, describe, expect, it } from "vitest";
import { useArchivingTasksStore } from "./archivingTasksStore";

describe("archivingTasksStore", () => {
  beforeEach(() => {
    useArchivingTasksStore.setState({
      archivingTaskIds: new Set(),
      hiddenArchivingTaskIds: new Set(),
    });
  });

  it("marks a task as archiving and back", () => {
    const { startArchiving, stopArchiving } = useArchivingTasksStore.getState();

    startArchiving("task-1");
    expect(useArchivingTasksStore.getState().isArchiving("task-1")).toBe(true);

    stopArchiving("task-1");
    expect(useArchivingTasksStore.getState().isArchiving("task-1")).toBe(false);
  });

  it("tracks multiple tasks independently", () => {
    const { startArchiving } = useArchivingTasksStore.getState();

    startArchiving("task-1");
    startArchiving("task-2");

    const state = useArchivingTasksStore.getState();
    expect(state.isArchiving("task-1")).toBe(true);
    expect(state.isArchiving("task-2")).toBe(true);
    expect(state.isArchiving("task-3")).toBe(false);
  });

  it("distinguishes bulk rows that disappear from single-task progress", () => {
    const { startArchiving } = useArchivingTasksStore.getState();

    startArchiving("single-task");
    startArchiving("bulk-task", "hidden");

    const state = useArchivingTasksStore.getState();
    expect(state.shouldHideWhileArchiving("single-task")).toBe(false);
    expect(state.shouldHideWhileArchiving("bulk-task")).toBe(true);
  });

  it("is idempotent and keeps a stable reference when nothing changes", () => {
    const { startArchiving, stopArchiving } = useArchivingTasksStore.getState();

    startArchiving("task-1");
    const setAfterStart = useArchivingTasksStore.getState().archivingTaskIds;

    // Starting an already-archiving task does not replace the set.
    startArchiving("task-1");
    expect(useArchivingTasksStore.getState().archivingTaskIds).toBe(
      setAfterStart,
    );

    // Stopping a task that isn't archiving is a no-op.
    stopArchiving("task-2");
    expect(useArchivingTasksStore.getState().archivingTaskIds).toBe(
      setAfterStart,
    );
  });
});
