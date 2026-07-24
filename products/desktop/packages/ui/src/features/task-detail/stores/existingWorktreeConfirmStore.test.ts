import { beforeEach, describe, expect, it } from "vitest";
import { useExistingWorktreeConfirmStore } from "./existingWorktreeConfirmStore";

describe("existingWorktreeConfirmStore", () => {
  beforeEach(() => {
    useExistingWorktreeConfirmStore.setState({
      isOpen: false,
      branch: null,
      worktreePath: null,
      resolve: null,
    });
  });

  it("starts closed", () => {
    const state = useExistingWorktreeConfirmStore.getState();
    expect(state.isOpen).toBe(false);
    expect(state.branch).toBeNull();
    expect(state.worktreePath).toBeNull();
  });

  it("confirm opens the dialog with the branch and path", () => {
    void useExistingWorktreeConfirmStore
      .getState()
      .confirm("feature/x", "/wt/feature-x");
    const state = useExistingWorktreeConfirmStore.getState();
    expect(state.isOpen).toBe(true);
    expect(state.branch).toBe("feature/x");
    expect(state.worktreePath).toBe("/wt/feature-x");
  });

  it("accept resolves the pending promise with true and closes", async () => {
    const promise = useExistingWorktreeConfirmStore
      .getState()
      .confirm("feature/x", "/wt/feature-x");
    useExistingWorktreeConfirmStore.getState().accept();
    await expect(promise).resolves.toBe(true);
    const state = useExistingWorktreeConfirmStore.getState();
    expect(state.isOpen).toBe(false);
    expect(state.branch).toBeNull();
    expect(state.worktreePath).toBeNull();
    expect(state.resolve).toBeNull();
  });

  it("cancel resolves the pending promise with false and closes", async () => {
    const promise = useExistingWorktreeConfirmStore
      .getState()
      .confirm("feature/x", "/wt/feature-x");
    useExistingWorktreeConfirmStore.getState().cancel();
    await expect(promise).resolves.toBe(false);
    expect(useExistingWorktreeConfirmStore.getState().isOpen).toBe(false);
  });

  it("opening a second dialog resolves the first as cancelled", async () => {
    const first = useExistingWorktreeConfirmStore
      .getState()
      .confirm("first", "/wt/first");
    const second = useExistingWorktreeConfirmStore
      .getState()
      .confirm("second", "/wt/second");
    await expect(first).resolves.toBe(false);
    expect(useExistingWorktreeConfirmStore.getState().worktreePath).toBe(
      "/wt/second",
    );
    useExistingWorktreeConfirmStore.getState().accept();
    await expect(second).resolves.toBe(true);
  });
});
