import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockUseWorkspace = vi.hoisted(() =>
  vi.fn((): { branchName: string; linkedBranch: string | null } | null => null),
);
vi.mock("./useWorkspace", () => ({ useWorkspace: mockUseWorkspace }));

import {
  useBranchMismatchGuard,
  useBranchWarningStore,
} from "./useBranchMismatch";

describe("useBranchWarningStore", () => {
  beforeEach(() => {
    useBranchWarningStore.setState({ dismissed: {} });
  });

  it("starts with no dismissed tasks", () => {
    expect(useBranchWarningStore.getState().dismissed).toEqual({});
  });

  it("dismiss marks task as dismissed", () => {
    useBranchWarningStore.getState().dismiss("task-1");
    expect(useBranchWarningStore.getState().dismissed["task-1"]).toBe(true);
  });

  it("reset clears dismissed for a task", () => {
    useBranchWarningStore.getState().dismiss("task-1");
    useBranchWarningStore.getState().reset("task-1");
    expect(useBranchWarningStore.getState().dismissed["task-1"]).toBe(false);
  });

  it("dismiss/reset are independent per task", () => {
    useBranchWarningStore.getState().dismiss("task-1");
    useBranchWarningStore.getState().dismiss("task-2");
    useBranchWarningStore.getState().reset("task-1");

    expect(useBranchWarningStore.getState().dismissed["task-1"]).toBe(false);
    expect(useBranchWarningStore.getState().dismissed["task-2"]).toBe(true);
  });
});

describe("useBranchMismatchGuard", () => {
  beforeEach(() => {
    useBranchWarningStore.setState({ dismissed: {} });
    mockUseWorkspace.mockReturnValue(null);
  });

  it("shouldWarn is false when no workspace", () => {
    const { result } = renderHook(() => useBranchMismatchGuard("task-1"));
    expect(result.current.shouldWarn).toBe(false);
  });

  it("shouldWarn is false when no linked branch", () => {
    mockUseWorkspace.mockReturnValue({
      branchName: "main",
      linkedBranch: null,
    });
    const { result } = renderHook(() => useBranchMismatchGuard("task-1"));
    expect(result.current.shouldWarn).toBe(false);
  });

  it("shouldWarn is false when branches match", () => {
    mockUseWorkspace.mockReturnValue({
      branchName: "feat/foo",
      linkedBranch: "feat/foo",
    });
    const { result } = renderHook(() => useBranchMismatchGuard("task-1"));
    expect(result.current.shouldWarn).toBe(false);
  });

  it("shouldWarn is true when branches mismatch", () => {
    mockUseWorkspace.mockReturnValue({
      branchName: "main",
      linkedBranch: "feat/foo",
    });
    const { result } = renderHook(() => useBranchMismatchGuard("task-1"));

    expect(result.current.shouldWarn).toBe(true);
    expect(result.current.linkedBranch).toBe("feat/foo");
    expect(result.current.currentBranch).toBe("main");
  });

  it("dismissWarning stops shouldWarn", () => {
    mockUseWorkspace.mockReturnValue({
      branchName: "main",
      linkedBranch: "feat/foo",
    });
    const { result } = renderHook(() => useBranchMismatchGuard("task-1"));
    expect(result.current.shouldWarn).toBe(true);

    act(() => result.current.dismissWarning());

    expect(result.current.shouldWarn).toBe(false);
  });

  it("shouldWarn resets when currentBranch changes", () => {
    mockUseWorkspace.mockReturnValue({
      branchName: "main",
      linkedBranch: "feat/foo",
    });
    const { result, rerender } = renderHook(() =>
      useBranchMismatchGuard("task-1"),
    );

    act(() => result.current.dismissWarning());
    expect(result.current.shouldWarn).toBe(false);

    // Simulate switching to a different (still mismatched) branch
    mockUseWorkspace.mockReturnValue({
      branchName: "develop",
      linkedBranch: "feat/foo",
    });
    rerender();

    expect(result.current.shouldWarn).toBe(true);
  });

  it("shouldWarn is false after switching to the linked branch", () => {
    mockUseWorkspace.mockReturnValue({
      branchName: "main",
      linkedBranch: "feat/foo",
    });
    const { result, rerender } = renderHook(() =>
      useBranchMismatchGuard("task-1"),
    );
    expect(result.current.shouldWarn).toBe(true);

    mockUseWorkspace.mockReturnValue({
      branchName: "feat/foo",
      linkedBranch: "feat/foo",
    });
    rerender();

    expect(result.current.shouldWarn).toBe(false);
  });
});
