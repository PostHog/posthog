import {
  workspaceInfoSchema,
  workspaceModeSchema,
  workspaceSchema,
  worktreeInfoSchema,
} from "@posthog/shared";
import { z } from "zod";

export {
  workspaceInfoSchema,
  workspaceModeSchema,
  workspaceSchema,
  worktreeInfoSchema,
};

// Input schemas
export const createWorkspaceInput = z
  .object({
    taskId: z.string(),
    mainRepoPath: z.string(),
    folderId: z.string(),
    folderPath: z.string(),
    mode: workspaceModeSchema,
    branch: z.string().optional(),
    useExistingBranch: z.boolean().optional(),
    // When set, a worktree branch that exists only on the remote is fetched and
    // checked out locally instead of failing. Gated behind a user confirmation.
    allowRemoteBranchCheckout: z.boolean().optional(),
    // When set, an existing worktree already checked out on the branch is reused
    // for the task instead of creating a new one. Gated behind a confirmation.
    reuseExistingWorktree: z.boolean().optional(),
  })
  .refine(
    (data) =>
      data.mode === "cloud" ||
      (data.mainRepoPath.length >= 2 && data.folderPath.length >= 2),
    {
      message: "Repository and folder paths must be valid for non-cloud mode",
    },
  );

export const checkWorktreeBranchInput = z.object({
  mainRepoPath: z.string(),
  branch: z.string(),
});

export const checkWorktreeBranchOutput = z.object({
  // "trunk": the default branch (handled by the normal detached-worktree path).
  // "local": branch exists locally. "remote-only": exists on the remote but not
  // locally. "missing": found neither locally nor on the remote.
  status: z.enum(["trunk", "local", "remote-only", "missing"]),
  // Path of an *unused* worktree already checked out on this branch, if any.
  // Set only when no task is associated with it; the renderer offers to reuse
  // it. Null when there is no managed worktree, or when one exists but is
  // already taken by a task (see existingWorktreeTaskId).
  existingWorktreePath: z.string().nullable(),
  // Id of the task already using the managed worktree on this branch, if any.
  // When set, the renderer blocks reuse and points the user at that task.
  // Mutually exclusive with existingWorktreePath.
  existingWorktreeTaskId: z.string().nullable(),
});

export const reconcileCloudWorkspacesInput = z.object({
  taskIds: z.array(z.string()),
});

export const reconcileCloudWorkspacesOutput = z.object({
  created: z.array(z.string()),
});

export const deleteWorkspaceInput = z.object({
  taskId: z.string(),
  mainRepoPath: z.string(),
});

export const verifyWorkspaceInput = z.object({
  taskId: z.string(),
});

export const ensureScratchDirInput = z.object({
  taskId: z.string(),
});

export const ensureScratchDirOutput = z.object({
  path: z.string(),
});

export const getWorkspaceInfoInput = z.object({
  taskId: z.string(),
});

// Output schemas
export const createWorkspaceOutput = workspaceInfoSchema;
export const verifyWorkspaceOutput = z.object({
  exists: z.boolean(),
  missingPath: z.string().optional(),
});
export const getWorkspaceInfoOutput = workspaceInfoSchema.nullable();
export const getAllWorkspacesOutput = z.record(z.string(), workspaceSchema);

export const workspaceErrorPayload = z.object({
  taskId: z.string(),
  message: z.string(),
});

export const workspaceWarningPayload = z.object({
  taskId: z.string(),
  title: z.string(),
  message: z.string(),
});

export const workspacePromotedPayload = z.object({
  taskId: z.string(),
  worktree: worktreeInfoSchema,
  fromBranch: z.string(),
});

export const branchChangedPayload = z.object({
  taskId: z.string(),
  branchName: z.string().nullable(),
});

export const linkedBranchChangedPayload = z.object({
  taskId: z.string(),
  branchName: z.string().nullable(),
});

export const taskPrInfoChangedPayload = z.object({
  taskId: z.string(),
  prUrl: z.string().nullable(),
  prUrls: z.array(z.string()).optional(),
  prState: z.enum(["merged", "open", "draft", "closed"]).nullable(),
});

export const linkBranchInput = z.object({
  taskId: z.string(),
  branchName: z.string(),
});

export const unlinkBranchInput = z.object({
  taskId: z.string(),
});

export const localBackgroundedPayload = z.object({
  mainRepoPath: z.string(),
  localWorktreePath: z.string(),
  branch: z.string(),
});

export const localForegroundedPayload = z.object({
  mainRepoPath: z.string(),
});

// Input/output schemas for local workspace backgrounding
export const isLocalBackgroundedInput = z.object({
  mainRepoPath: z.string(),
});

export const isLocalBackgroundedOutput = z.boolean();

export const getLocalWorktreePathInput = z.object({
  mainRepoPath: z.string(),
});

export const getLocalWorktreePathOutput = z.string();

export const backgroundLocalWorkspaceInput = z.object({
  mainRepoPath: z.string(),
  branch: z.string(),
});

export const backgroundLocalWorkspaceOutput = z.string().nullable();

export const foregroundLocalWorkspaceInput = z.object({
  mainRepoPath: z.string(),
});

export const foregroundLocalWorkspaceOutput = z.boolean();

export const getLocalTasksInput = z.object({
  mainRepoPath: z.string(),
});

export const localTaskSchema = z.object({
  taskId: z.string(),
});

export const getLocalTasksOutput = z.array(localTaskSchema);

export const getWorktreeTasksInput = z.object({
  worktreePath: z.string(),
});

export const getWorktreeTasksOutput = z.array(localTaskSchema);

export const listGitWorktreesInput = z.object({
  mainRepoPath: z.string(),
});

export const getWorktreeFileUsageInput = z.object({
  mainRepoPath: z.string(),
});

export const getWorktreeFileUsageOutput = z.object({
  usesWorktreeLink: z.boolean(),
  usesWorktreeInclude: z.boolean(),
});

export const gitWorktreeEntrySchema = z.object({
  worktreePath: z.string(),
  head: z.string(),
  branch: z.string().nullable(),
  taskIds: z.array(z.string()),
});

export const listGitWorktreesOutput = z.array(gitWorktreeEntrySchema);

export const listRepoCheckoutsInput = z.object({
  repoPath: z.string(),
});

export const repoCheckoutSchema = z.object({
  path: z.string(),
  branch: z.string().nullable(),
});

export const listRepoCheckoutsOutput = z.array(repoCheckoutSchema);

export const listAdoptableWorktreesInput = z.object({
  mainRepoPath: z.string(),
});

// A task-less linked worktree the sidebar offers to start a task in.
export const adoptableWorktreeSchema = z.object({
  worktreePath: z.string(),
  branch: z.string(),
});

export const listAdoptableWorktreesOutput = z.array(adoptableWorktreeSchema);

export const getWorktreeSizeInput = z.object({
  worktreePath: z.string(),
});

export const getWorktreeSizeOutput = z.object({
  sizeBytes: z.number(),
});

export const deleteWorktreeInput = z.object({
  worktreePath: z.string(),
  mainRepoPath: z.string(),
});

export const togglePinInput = z.object({
  taskId: z.string(),
});

export const togglePinOutput = z.object({
  isPinned: z.boolean(),
  pinnedAt: z.string().nullable(),
});

export const markViewedInput = z.object({
  taskId: z.string(),
});

export const markActivityInput = z.object({
  taskId: z.string(),
});

export const getPinnedTaskIdsOutput = z.array(z.string());

export const getTaskTimestampsInput = z.object({
  taskId: z.string(),
});

export const getTaskTimestampsOutput = z.object({
  pinnedAt: z.string().nullable(),
  lastViewedAt: z.string().nullable(),
  lastActivityAt: z.string().nullable(),
});

export const getAllTaskTimestampsOutput = z.record(
  z.string(),
  z.object({
    pinnedAt: z.string().nullable(),
    lastViewedAt: z.string().nullable(),
    lastActivityAt: z.string().nullable(),
  }),
);

// Task PR status
export const taskPrStatusInput = z.object({
  taskId: z.string(),
  cloudPrUrl: z.string().nullable(),
});

export const cachedPrUrlInput = z.object({
  taskId: z.string(),
});

export const cachedPrUrlOutput = z.object({
  prUrl: z.string().nullable(),
  prUrls: z.array(z.string()),
});

export const setPrimaryPrUrlInput = z.object({
  taskId: z.string(),
  prUrl: z.string(),
});

export const sidebarPrStateSchema = z
  .enum(["merged", "open", "draft", "closed"])
  .nullable();

export const taskPrStatusOutput = z.object({
  prState: sidebarPrStateSchema,
  hasDiff: z.boolean(),
});

export type TaskPrStatusInput = z.infer<typeof taskPrStatusInput>;
export type SidebarPrState = z.infer<typeof sidebarPrStateSchema>;
export type TaskPrStatus = z.infer<typeof taskPrStatusOutput>;
export type CachedPrUrlInput = z.infer<typeof cachedPrUrlInput>;
export type CachedPrUrlOutput = z.infer<typeof cachedPrUrlOutput>;

// Type exports
export type {
  Workspace,
  WorkspaceInfo,
  WorkspaceMode,
  WorktreeInfo,
} from "@posthog/shared";

export type CreateWorkspaceInput = z.infer<typeof createWorkspaceInput>;
export type CheckWorktreeBranchInput = z.infer<typeof checkWorktreeBranchInput>;
export type CheckWorktreeBranchOutput = z.infer<
  typeof checkWorktreeBranchOutput
>;
export type ReconcileCloudWorkspacesInput = z.infer<
  typeof reconcileCloudWorkspacesInput
>;
export type ReconcileCloudWorkspacesOutput = z.infer<
  typeof reconcileCloudWorkspacesOutput
>;
export type DeleteWorkspaceInput = z.infer<typeof deleteWorkspaceInput>;
export type VerifyWorkspaceInput = z.infer<typeof verifyWorkspaceInput>;
export type GetWorkspaceInfoInput = z.infer<typeof getWorkspaceInfoInput>;
export type ListGitWorktreesInput = z.infer<typeof listGitWorktreesInput>;
export type ListRepoCheckoutsInput = z.infer<typeof listRepoCheckoutsInput>;
export type RepoCheckout = z.infer<typeof repoCheckoutSchema>;
export type AdoptableWorktree = z.infer<typeof adoptableWorktreeSchema>;
export type GetWorktreeSizeInput = z.infer<typeof getWorktreeSizeInput>;
export type DeleteWorktreeInput = z.infer<typeof deleteWorktreeInput>;
export type WorkspaceErrorPayload = z.infer<typeof workspaceErrorPayload>;
export type WorkspaceWarningPayload = z.infer<typeof workspaceWarningPayload>;
export type WorkspacePromotedPayload = z.infer<typeof workspacePromotedPayload>;
export type BranchChangedPayload = z.infer<typeof branchChangedPayload>;
export type LinkedBranchChangedPayload = z.infer<
  typeof linkedBranchChangedPayload
>;
export type TaskPrInfoChangedPayload = z.infer<typeof taskPrInfoChangedPayload>;
export type LinkBranchInput = z.infer<typeof linkBranchInput>;
export type UnlinkBranchInput = z.infer<typeof unlinkBranchInput>;
export type LocalBackgroundedPayload = z.infer<typeof localBackgroundedPayload>;
export type LocalForegroundedPayload = z.infer<typeof localForegroundedPayload>;
export type IsLocalBackgroundedInput = z.infer<typeof isLocalBackgroundedInput>;
export type GetLocalWorktreePathInput = z.infer<
  typeof getLocalWorktreePathInput
>;
