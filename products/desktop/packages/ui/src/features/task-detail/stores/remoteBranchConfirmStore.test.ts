import { beforeEach, describe, expect, it } from "vitest";
import { useRemoteBranchConfirmStore } from "./remoteBranchConfirmStore";

describe("remoteBranchConfirmStore", () => {
  beforeEach(() => {
    useRemoteBranchConfirmStore.setState({
      isOpen: false,
      branch: null,
      resolve: null,
    });
  });

  it("starts closed", () => {
    const state = useRemoteBranchConfirmStore.getState();
    expect(state.isOpen).toBe(false);
    expect(state.branch).toBeNull();
  });

  it("confirm opens the dialog with the branch", () => {
    const promise = useRemoteBranchConfirmStore.getState().confirm("feature/x");
    const state = useRemoteBranchConfirmStore.getState();
    expect(state.isOpen).toBe(true);
    expect(state.branch).toBe("feature/x");
    // Resolve the pending promise so it doesn't dangle past this test.
    useRemoteBranchConfirmStore.getState().cancel();
    return expect(promise).resolves.toBe(false);
  });

  it.each([
    { action: "accept" as const, expected: true },
    { action: "cancel" as const, expected: false },
  ])(
    "$action resolves the pending promise with $expected and closes",
    async ({ action, expected }) => {
      const promise = useRemoteBranchConfirmStore
        .getState()
        .confirm("feature/x");
      useRemoteBranchConfirmStore.getState()[action]();
      await expect(promise).resolves.toBe(expected);
      const state = useRemoteBranchConfirmStore.getState();
      expect(state.isOpen).toBe(false);
      expect(state.branch).toBeNull();
      expect(state.resolve).toBeNull();
    },
  );

  it("opening a second dialog resolves the first as cancelled", async () => {
    const first = useRemoteBranchConfirmStore.getState().confirm("first");
    const second = useRemoteBranchConfirmStore.getState().confirm("second");
    await expect(first).resolves.toBe(false);
    expect(useRemoteBranchConfirmStore.getState().branch).toBe("second");
    useRemoteBranchConfirmStore.getState().accept();
    await expect(second).resolves.toBe(true);
  });
});
