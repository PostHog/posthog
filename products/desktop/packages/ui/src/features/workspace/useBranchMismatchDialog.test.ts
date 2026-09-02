import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let mockShouldWarn = false;
const mockDismissWarning = vi.fn();

const mockGuard = vi.hoisted(() => ({
  useBranchMismatchGuard: vi.fn(
    (): {
      shouldWarn: boolean;
      linkedBranch: string | null;
      currentBranch: string | null;
      dismissWarning: () => void;
    } => ({
      shouldWarn: mockShouldWarn,
      linkedBranch: "feat/foo",
      currentBranch: "main",
      dismissWarning: mockDismissWarning,
    }),
  ),
}));
vi.mock("./useBranchMismatch", () => mockGuard);

vi.mock("../git-interaction/useGitQueries", () => ({
  useGitQueries: () => ({ hasChanges: false }),
}));

vi.mock("../git-interaction/gitCacheKeys", () => ({
  invalidateGitBranchQueries: vi.fn(),
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    git: {
      checkoutBranch: {
        mutationOptions: (opts: Record<string, unknown>) => opts,
      },
    },
  }),
}));

let capturedMutationOptions: {
  onSuccess?: () => void;
  onError?: (e: Error) => void;
} = {};
const mockMutate = vi.fn();
let mockIsPending = false;

vi.mock("@tanstack/react-query", () => ({
  useMutation: (opts: Record<string, unknown>) => {
    capturedMutationOptions = opts as typeof capturedMutationOptions;
    return { mutate: mockMutate, isPending: mockIsPending };
  },
}));

vi.mock("../../shell/logger", () => ({
  logger: { scope: () => ({ error: vi.fn() }) },
}));

const mockTrack = vi.fn();
vi.mock("../../shell/analytics", () => ({
  track: (...args: unknown[]) => mockTrack(...args),
}));

import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useBranchMismatchDialog } from "./useBranchMismatchDialog";

function renderDialog(overrides?: { shouldWarn?: boolean }) {
  mockShouldWarn = overrides?.shouldWarn ?? false;
  mockGuard.useBranchMismatchGuard.mockReturnValue({
    shouldWarn: mockShouldWarn,
    linkedBranch: "feat/foo",
    currentBranch: "main",
    dismissWarning: mockDismissWarning,
  });

  const onSendPrompt = vi.fn();
  const hook = renderHook(() =>
    useBranchMismatchDialog({
      taskId: "task-1",
      repoPath: "/repo",
      onSendPrompt,
    }),
  );
  return { ...hook, onSendPrompt };
}

describe("useBranchMismatchDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedMutationOptions = {};
    mockShouldWarn = false;
    mockIsPending = false;
  });

  describe("handleBeforeSubmit", () => {
    it("returns true when shouldWarn is false", () => {
      const { result } = renderDialog({ shouldWarn: false });
      const clearEditor = vi.fn();

      const allowed = result.current.handleBeforeSubmit("hello", clearEditor);

      expect(allowed).toBe(true);
      expect(result.current.dialogProps?.open).toBeFalsy();
    });

    it("returns false and opens dialog when shouldWarn is true", () => {
      const { result } = renderDialog({ shouldWarn: true });
      const clearEditor = vi.fn();

      let allowed = true;
      act(() => {
        allowed = result.current.handleBeforeSubmit("hello", clearEditor);
      });

      expect(allowed).toBe(false);
      expect(result.current.dialogProps?.open).toBe(true);
      expect(clearEditor).not.toHaveBeenCalled();
      expect(mockTrack).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.BRANCH_MISMATCH_WARNING_SHOWN,
        {
          task_id: "task-1",
          linked_branch: "feat/foo",
          current_branch: "main",
          has_uncommitted_changes: false,
        },
      );
    });
  });

  describe("handleContinue", () => {
    it("sends the pending message and clears editor", () => {
      const { result, onSendPrompt } = renderDialog({ shouldWarn: true });
      const clearEditor = vi.fn();

      act(() => {
        result.current.handleBeforeSubmit("hello", clearEditor);
      });

      mockTrack.mockClear();
      act(() => {
        result.current.dialogProps?.onContinue();
      });

      expect(onSendPrompt).toHaveBeenCalledWith("hello");
      expect(clearEditor).toHaveBeenCalled();
      expect(mockDismissWarning).toHaveBeenCalled();
      expect(result.current.dialogProps?.open).toBe(false);
      expect(mockTrack).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.BRANCH_MISMATCH_ACTION,
        {
          task_id: "task-1",
          action: "continue",
          linked_branch: "feat/foo",
          current_branch: "main",
        },
      );
    });
  });

  describe("handleCancel", () => {
    it("clears state without sending or clearing editor", () => {
      const { result, onSendPrompt } = renderDialog({ shouldWarn: true });
      const clearEditor = vi.fn();

      act(() => {
        result.current.handleBeforeSubmit("hello", clearEditor);
      });
      expect(result.current.dialogProps?.open).toBe(true);

      mockTrack.mockClear();
      act(() => {
        result.current.dialogProps?.onCancel();
      });

      expect(onSendPrompt).not.toHaveBeenCalled();
      expect(clearEditor).not.toHaveBeenCalled();
      expect(result.current.dialogProps?.open).toBe(false);
      expect(mockTrack).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.BRANCH_MISMATCH_ACTION,
        {
          task_id: "task-1",
          action: "cancel",
          linked_branch: "feat/foo",
          current_branch: "main",
        },
      );
    });

    it("does nothing while a switch is in flight, so a dismiss can't drop the pending message", () => {
      mockIsPending = true;
      const { result, onSendPrompt } = renderDialog({ shouldWarn: true });
      const clearEditor = vi.fn();

      act(() => {
        result.current.handleBeforeSubmit("hello", clearEditor);
      });

      act(() => {
        result.current.dialogProps?.onSwitch();
      });

      mockTrack.mockClear();
      act(() => {
        result.current.dialogProps?.onCancel();
      });

      expect(mockTrack).not.toHaveBeenCalled();
      expect(result.current.dialogProps?.open).toBe(true);

      act(() => {
        capturedMutationOptions.onSuccess?.();
      });

      expect(onSendPrompt).toHaveBeenCalledWith("hello");
    });
  });

  describe("handleSwitch", () => {
    it("calls checkoutBranch mutation and tracks switch action", () => {
      const { result } = renderDialog({ shouldWarn: true });
      const clearEditor = vi.fn();

      act(() => {
        result.current.handleBeforeSubmit("hello", clearEditor);
      });

      mockTrack.mockClear();
      act(() => {
        result.current.dialogProps?.onSwitch();
      });

      expect(mockMutate).toHaveBeenCalledWith({
        directoryPath: "/repo",
        branchName: "feat/foo",
      });
      expect(mockTrack).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.BRANCH_MISMATCH_ACTION,
        {
          task_id: "task-1",
          action: "switch",
          linked_branch: "feat/foo",
          current_branch: "main",
        },
      );
    });

    it("on success: sends pending message and clears editor", () => {
      const { result, onSendPrompt } = renderDialog({ shouldWarn: true });
      const clearEditor = vi.fn();

      act(() => {
        result.current.handleBeforeSubmit("hello", clearEditor);
      });

      act(() => {
        result.current.dialogProps?.onSwitch();
      });

      // Simulate mutation success
      act(() => {
        capturedMutationOptions.onSuccess?.();
      });

      expect(onSendPrompt).toHaveBeenCalledWith("hello");
      expect(clearEditor).toHaveBeenCalled();
      expect(mockDismissWarning).toHaveBeenCalled();
    });

    it("on error: shows error without sending message", () => {
      const { result, onSendPrompt } = renderDialog({ shouldWarn: true });
      const clearEditor = vi.fn();

      act(() => {
        result.current.handleBeforeSubmit("hello", clearEditor);
      });

      act(() => {
        result.current.dialogProps?.onSwitch();
      });

      act(() => {
        capturedMutationOptions.onError?.(new Error("dirty worktree"));
      });

      expect(onSendPrompt).not.toHaveBeenCalled();
      expect(clearEditor).not.toHaveBeenCalled();
      expect(result.current.dialogProps?.switchError).toBe("dirty worktree");
    });
  });

  describe("dialogProps", () => {
    it("is null when no linked branch", () => {
      mockGuard.useBranchMismatchGuard.mockReturnValue({
        shouldWarn: false,
        linkedBranch: null,
        currentBranch: "main",
        dismissWarning: mockDismissWarning,
      });

      const { result } = renderHook(() =>
        useBranchMismatchDialog({
          taskId: "task-1",
          repoPath: "/repo",
          onSendPrompt: vi.fn(),
        }),
      );

      expect(result.current.dialogProps).toBeNull();
    });
  });
});
