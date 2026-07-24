import { z } from "zod";

export const focusResultSchema = z.object({
  success: z.boolean(),
  error: z.string().optional(),
  stashPopWarning: z.string().optional(),
});

export type FocusResult = z.infer<typeof focusResultSchema>;

export const stashResultSchema = focusResultSchema.extend({
  stashRef: z.string().optional(),
});

export type StashResult = z.infer<typeof stashResultSchema>;

export const focusSessionSchema = z.object({
  mainRepoPath: z.string(),
  worktreePath: z.string(),
  branch: z.string(),
  originalBranch: z.string(),
  mainStashRef: z.string().nullable(),
  commitSha: z.string(),
});

export type FocusSession = z.infer<typeof focusSessionSchema>;

export const focusBranchRenamedEventSchema = z.object({
  mainRepoPath: z.string(),
  worktreePath: z.string(),
  oldBranch: z.string(),
  newBranch: z.string(),
});

export type FocusBranchRenamedEvent = z.infer<
  typeof focusBranchRenamedEventSchema
>;

export const focusForeignBranchCheckoutEventSchema = z.object({
  mainRepoPath: z.string(),
  worktreePath: z.string(),
  focusedBranch: z.string(),
  foreignBranch: z.string(),
});

export type FocusForeignBranchCheckoutEvent = z.infer<
  typeof focusForeignBranchCheckoutEventSchema
>;

export const repoPathInput = z.object({ repoPath: z.string() });
export const mainRepoPathInput = z.object({ mainRepoPath: z.string() });
export const stashInput = z.object({
  repoPath: z.string(),
  message: z.string(),
});
export const checkoutInput = z.object({
  repoPath: z.string(),
  branch: z.string(),
});
export const worktreeInput = z.object({ worktreePath: z.string() });
export const reattachInput = z.object({
  worktreePath: z.string(),
  branch: z.string(),
});
export const syncInput = z.object({
  mainRepoPath: z.string(),
  worktreePath: z.string(),
});
export const findWorktreeInput = z.object({
  mainRepoPath: z.string(),
  branch: z.string(),
});
