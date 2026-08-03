import { z } from "zod";

export const directoryPathInput = z.object({ directoryPath: z.string() });

export const diffStatsInput = z.object({ directoryPath: z.string().min(1) });

export const diffStatsSchema = z.object({
  filesChanged: z.number().int().nonnegative(),
  linesAdded: z.number().int().nonnegative(),
  linesRemoved: z.number().int().nonnegative(),
});

export type DiffStats = z.infer<typeof diffStatsSchema>;

export const gitFileStatusSchema = z.enum([
  "modified",
  "added",
  "deleted",
  "renamed",
  "untracked",
]);

export type GitFileStatus = z.infer<typeof gitFileStatusSchema>;

export const changedFileSchema = z.object({
  path: z.string(),
  status: gitFileStatusSchema,
  originalPath: z.string().optional(),
  linesAdded: z.number().optional(),
  linesRemoved: z.number().optional(),
  staged: z.boolean().optional(),
  patch: z.string().optional(),
  sha: z.string().optional(),
});

export type ChangedFile = z.infer<typeof changedFileSchema>;

export const gitCommitInfoSchema = z.object({
  sha: z.string(),
  shortSha: z.string(),
  message: z.string(),
  author: z.string(),
  date: z.string(),
});

export type GitCommitInfo = z.infer<typeof gitCommitInfoSchema>;

export const gitRepoInfoSchema = z.object({
  organization: z.string(),
  repository: z.string(),
  currentBranch: z.string().nullable(),
  defaultBranch: z.string(),
  compareUrl: z.string().nullable(),
});

export type GitRepoInfo = z.infer<typeof gitRepoInfoSchema>;

export const detectRepoResultSchema = z
  .object({
    organization: z.string(),
    repository: z.string(),
    remote: z.string().optional(),
    branch: z.string().optional(),
  })
  .nullable();

export type DetectRepoResult = z.infer<typeof detectRepoResultSchema>;

export const filePathInput = z.object({
  directoryPath: z.string(),
  filePath: z.string(),
});

export const diffInput = z.object({
  directoryPath: z.string(),
  ignoreWhitespace: z.boolean().optional(),
});

export const stringNullableOutput = z.string().nullable();
export const stringOutput = z.string();
export const stringArrayOutput = z.array(z.string());
export const changedFilesOutput = z.array(changedFileSchema);
export const gitCommitInfoNullableOutput = gitCommitInfoSchema.nullable();
export const gitRepoInfoNullableOutput = gitRepoInfoSchema.nullable();

// --- git-mutate group ---

export const gitSyncStatusSchema = z.object({
  aheadOfRemote: z.number(),
  behind: z.number(),
  aheadOfDefault: z.number(),
  hasRemote: z.boolean(),
  currentBranch: z.string().nullable(),
  isFeatureBranch: z.boolean(),
});

export type GitSyncStatus = z.infer<typeof gitSyncStatusSchema>;

export const gitBusyOperationSchema = z.enum([
  "rebase",
  "merge",
  "cherry-pick",
  "revert",
]);

export const gitBusyStateSchema = z.union([
  z.object({ busy: z.literal(false) }),
  z.object({
    busy: z.literal(true),
    operation: gitBusyOperationSchema,
  }),
]);

export const prStatusOutput = z.object({
  hasRemote: z.boolean(),
  isGitHubRepo: z.boolean(),
  currentBranch: z.string().nullable(),
  defaultBranch: z.string().nullable(),
  prExists: z.boolean(),
  prUrl: z.string().nullable(),
  prState: z.string().nullable(),
  baseBranch: z.string().nullable(),
  headBranch: z.string().nullable(),
  isDraft: z.boolean().nullable(),
  error: z.string().nullable(),
});

export const gitStateSnapshotSchema = z.object({
  changedFiles: z.array(changedFileSchema).optional(),
  diffStats: diffStatsSchema.optional(),
  syncStatus: gitSyncStatusSchema.optional(),
  latestCommit: gitCommitInfoSchema.nullable().optional(),
  prStatus: prStatusOutput.optional(),
});

export type GitStateSnapshot = z.infer<typeof gitStateSnapshotSchema>;

export const stageFilesInput = z.object({
  directoryPath: z.string(),
  paths: z.array(z.string()),
});

export const createBranchInput = z.object({
  directoryPath: z.string(),
  branchName: z.string(),
});

export const checkoutBranchInput = z.object({
  directoryPath: z.string(),
  branchName: z.string(),
});

export const checkoutBranchOutput = z.object({
  previousBranch: z.string(),
  currentBranch: z.string(),
});

export const discardFileChangesInput = z.object({
  directoryPath: z.string(),
  filePath: z.string(),
  fileStatus: gitFileStatusSchema,
});

export const discardFileChangesOutput = z.object({
  success: z.boolean(),
  state: gitStateSnapshotSchema.optional(),
});

export type DiscardFileChangesOutput = z.infer<typeof discardFileChangesOutput>;

export const discardAllChangesInput = z.object({
  directoryPath: z.string(),
});

export const getGitSyncStatusInput = z.object({
  directoryPath: z.string(),
  /**
   * Whether to run `git fetch` before reading sync status. Defaults to false:
   * background pollers should read local refs only so that idle UI does not
   * keep hitting the network (and, transitively, ssh-agent). Set true at the
   * few callsites that genuinely need an up-to-date view of `origin/*`.
   */
  fetchFromRemote: z.boolean().optional(),
});

export const gitBusyStateInput = directoryPathInput;

export const pushInput = z.object({
  directoryPath: z.string(),
  remote: z.string().default("origin"),
  branch: z.string().optional(),
  setUpstream: z.boolean().default(false),
  env: z.record(z.string(), z.string()).optional(),
});

export const pushOutput = z.object({
  success: z.boolean(),
  message: z.string(),
  state: gitStateSnapshotSchema.optional(),
});

export type PushOutput = z.infer<typeof pushOutput>;

export const commitInput = z.object({
  directoryPath: z.string(),
  message: z.string(),
  paths: z.array(z.string()).optional(),
  allowEmpty: z.boolean().optional(),
  stagedOnly: z.boolean().optional(),
  // Pre-resolved SessionStart-hook env (e.g. SSH_AUTH_SOCK for commit signing),
  // resolved in the host process where AgentService runs and passed through.
  env: z.record(z.string(), z.string()).optional(),
});

export type CommitInput = z.infer<typeof commitInput>;

export const commitOutput = z.object({
  success: z.boolean(),
  message: z.string(),
  commitSha: z.string().nullable(),
  branch: z.string().nullable(),
  state: gitStateSnapshotSchema.optional(),
});

export type CommitOutput = z.infer<typeof commitOutput>;

export const pullInput = z.object({
  directoryPath: z.string(),
  remote: z.string().default("origin"),
  branch: z.string().optional(),
});

export const pullOutput = z.object({
  success: z.boolean(),
  message: z.string(),
  updatedFiles: z.number().optional(),
  state: gitStateSnapshotSchema.optional(),
});

export type PullOutput = z.infer<typeof pullOutput>;

export const publishInput = z.object({
  directoryPath: z.string(),
  remote: z.string().default("origin"),
  env: z.record(z.string(), z.string()).optional(),
});

export const publishOutput = z.object({
  success: z.boolean(),
  message: z.string(),
  branch: z.string(),
  state: gitStateSnapshotSchema.optional(),
});

export type PublishOutput = z.infer<typeof publishOutput>;

export const syncInput = z.object({
  directoryPath: z.string(),
  remote: z.string().default("origin"),
});

export const syncOutput = z.object({
  success: z.boolean(),
  pullMessage: z.string(),
  pushMessage: z.string(),
  state: gitStateSnapshotSchema.optional(),
});

export type SyncOutput = z.infer<typeof syncOutput>;

// --- git-pr group (pure gh-CLI PR/GitHub read ops) ---

export const ghStatusOutput = z.object({
  installed: z.boolean(),
  version: z.string().nullable(),
  authenticated: z.boolean(),
  username: z.string().nullable(),
  error: z.string().nullable(),
});

export type GhStatusOutput = z.infer<typeof ghStatusOutput>;

export const ghAuthTokenOutput = z.object({
  success: z.boolean(),
  token: z.string().nullable(),
  error: z.string().nullable(),
});

export type GhAuthTokenOutput = z.infer<typeof ghAuthTokenOutput>;

export type PrStatusOutput = z.infer<typeof prStatusOutput>;

export const getPrUrlForBranchInput = z.object({
  directoryPath: z.string(),
  branchName: z.string(),
});

export const getPrUrlForBranchOutput = z.string().nullable();

export const openPrInput = directoryPathInput;

export const openPrOutput = z.object({
  success: z.boolean(),
  message: z.string(),
  prUrl: z.string().nullable(),
});

export type OpenPrOutput = z.infer<typeof openPrOutput>;

export const getPrDetailsByUrlInput = z.object({ prUrl: z.string() });

export const getPrDetailsByUrlOutput = z.object({
  state: z.string(),
  merged: z.boolean(),
  draft: z.boolean(),
  headRefName: z.string().nullable(),
  title: z.string().nullable(),
});

export type PrDetailsByUrlOutput = z.infer<typeof getPrDetailsByUrlOutput>;

export const getPrChangedFilesInput = z.object({ prUrl: z.string() });

// Also carries the PR's live status (`state`/`merged`/`draft`) so list cards
// can render it from the single batched GraphQL request instead of firing one
// REST call per visible PR. Mirrors `prDiffStatsSchema` in
// `@posthog/core/git/router-schemas`.
export const prDiffStatsSchema = z.object({
  additions: z.number(),
  deletions: z.number(),
  changedFiles: z.number(),
  /** Lowercased GitHub PR state. */
  state: z.enum(["open", "closed", "merged"]),
  merged: z.boolean(),
  draft: z.boolean(),
});
export type PrDiffStats = z.infer<typeof prDiffStatsSchema>;

export const getPrDiffStatsBatchInput = z.object({
  prUrls: z.array(z.string()),
});
export const getPrDiffStatsBatchOutput = z.record(
  z.string(),
  prDiffStatsSchema,
);

export const getBranchChangedFilesInput = z.object({
  repo: z.string(),
  branch: z.string(),
});

export const getLocalBranchChangedFilesInput = z.object({
  directoryPath: z.string(),
  branch: z.string(),
});

export const prReviewCommentUserSchema = z.object({
  login: z.string(),
  avatar_url: z.string(),
});

export const prReviewCommentSchema = z.object({
  id: z.number(),
  body: z.string(),
  path: z.string(),
  line: z.number().nullable(),
  original_line: z.number().nullable(),
  side: z.enum(["LEFT", "RIGHT"]),
  start_line: z.number().nullable(),
  start_side: z.enum(["LEFT", "RIGHT"]).nullable(),
  diff_hunk: z.string(),
  in_reply_to_id: z.number().nullish(),
  user: prReviewCommentUserSchema,
  created_at: z.string(),
  updated_at: z.string(),
  subject_type: z.enum(["line", "file"]).nullable(),
});

export type PrReviewComment = z.infer<typeof prReviewCommentSchema>;

export const prReviewThreadSchema = z.object({
  nodeId: z.string(),
  isResolved: z.boolean(),
  rootId: z.number(),
  filePath: z.string(),
  comments: z.array(prReviewCommentSchema),
});

export type PrReviewThread = z.infer<typeof prReviewThreadSchema>;

export const getPrReviewCommentsInput = z.object({ prUrl: z.string() });
export const getPrReviewCommentsOutput = z.array(prReviewThreadSchema);

export const resolveReviewThreadInput = z.object({
  prUrl: z.string(),
  threadNodeId: z.string(),
  resolved: z.boolean(),
});

export const resolveReviewThreadOutput = z.object({
  success: z.boolean(),
  isResolved: z.boolean(),
});

export type ResolveReviewThreadOutput = z.infer<
  typeof resolveReviewThreadOutput
>;

export const replyToPrCommentInput = z.object({
  prUrl: z.string(),
  commentId: z.number(),
  body: z.string(),
});

export const replyToPrCommentOutput = z.object({
  success: z.boolean(),
  comment: prReviewCommentSchema.nullable(),
});

export type ReplyToPrCommentOutput = z.infer<typeof replyToPrCommentOutput>;

export const prActionType = z.enum(["close", "reopen", "ready", "draft"]);
export type PrActionType = z.infer<typeof prActionType>;

export const updatePrByUrlInput = z.object({
  prUrl: z.string(),
  action: prActionType,
});

export const updatePrByUrlOutput = z.object({
  success: z.boolean(),
  message: z.string(),
});

export type UpdatePrByUrlOutput = z.infer<typeof updatePrByUrlOutput>;

export type {
  ApprovePrOutput,
  GetPrChecksOutput,
  GetPrCommentsOutput,
  MergePrOutput,
  PrCheck,
  PrCheckBucket,
  PrConversationComment,
  PrInfoByUrlOutput,
  PrMergeMethod,
} from "@posthog/shared";
// Native PR review schemas (PR overview, approve/merge, CI checks,
// conversation comments) are defined once in `@posthog/shared`'s git domain
// and re-exported here for the tRPC procedure definitions and GitService.
export {
  approvePrInput,
  approvePrOutput,
  getPrChecksInput,
  getPrChecksOutput,
  getPrCommentsInput,
  getPrCommentsOutput,
  getPrInfoByUrlInput,
  getPrInfoByUrlOutput,
  mergePrInput,
  mergePrOutput,
  prCheckBucketSchema,
  prCheckSchema,
  prConversationCommentSchema,
  prMergeMethodSchema,
} from "@posthog/shared";

export const getPrTemplateInput = directoryPathInput;

export const getPrTemplateOutput = z.object({
  template: z.string().nullable(),
  templatePath: z.string().nullable(),
});

export type GetPrTemplateOutput = z.infer<typeof getPrTemplateOutput>;

export const getCommitConventionsInput = z.object({
  directoryPath: z.string(),
  sampleSize: z.number().default(20),
});

export const getCommitConventionsOutput = z.object({
  conventionalCommits: z.boolean(),
  commonPrefixes: z.array(z.string()),
  sampleMessages: z.array(z.string()),
});

export type GetCommitConventionsOutput = z.infer<
  typeof getCommitConventionsOutput
>;

export const githubRefKindSchema = z.enum(["issue", "pr"]);
export type GithubRefKind = z.infer<typeof githubRefKindSchema>;

export const githubRefStateSchema = z.enum(["OPEN", "CLOSED", "MERGED"]);

export const githubRefSchema = z.object({
  kind: githubRefKindSchema,
  number: z.number(),
  title: z.string(),
  state: githubRefStateSchema,
  labels: z.array(z.string()),
  url: z.string(),
  repo: z.string(),
  isDraft: z.boolean().optional(),
});

export type GithubRef = z.infer<typeof githubRefSchema>;

export const searchGithubRefsInput = z.object({
  directoryPath: z.string(),
  query: z.string().optional(),
  limit: z.number().default(25),
  kinds: z.array(githubRefKindSchema).optional(),
});

export const searchGithubRefsOutput = z.array(githubRefSchema);

export const getGithubIssueInput = z.object({
  owner: z.string(),
  repo: z.string(),
  number: z.number().int().positive(),
});

export const getGithubIssueOutput = githubRefSchema.nullable();

export const getGithubPullRequestInput = getGithubIssueInput;
export const getGithubPullRequestOutput = getGithubIssueOutput;

export const handoffLocalGitStateSchema = z.object({
  head: z.string().nullable(),
  branch: z.string().nullable(),
  upstreamHead: z.string().nullable(),
  upstreamRemote: z.string().nullable(),
  upstreamMergeRef: z.string().nullable(),
});

export type HandoffLocalGitState = z.infer<typeof handoffLocalGitStateSchema>;

export const readHandoffLocalGitStateInput = z.object({
  directoryPath: z.string(),
});
export const readHandoffLocalGitStateOutput = handoffLocalGitStateSchema;

export const cleanupAfterCloudHandoffInput = z.object({
  directoryPath: z.string(),
  branchName: z.string().nullable(),
});
export const cleanupAfterCloudHandoffOutput = z.object({
  stashed: z.boolean(),
  switched: z.boolean(),
  defaultBranch: z.string().nullable(),
});

export const gitStatusOutput = z.object({
  installed: z.boolean(),
  version: z.string().nullable(),
});
export type GitStatusOutput = z.infer<typeof gitStatusOutput>;

export const getHeadShaOutput = z.string();

export const resetSoftInput = z.object({
  directoryPath: z.string(),
  sha: z.string(),
});

export const createPrViaGhInput = z.object({
  directoryPath: z.string(),
  title: z.string().optional(),
  body: z.string().optional(),
  draft: z.boolean().optional(),
  env: z.record(z.string(), z.string()).optional(),
});
export const createPrViaGhOutput = z.object({
  success: z.boolean(),
  message: z.string(),
  prUrl: z.string().nullable(),
});

export const cloneRepositoryInput = z.object({
  repoUrl: z.string(),
  targetPath: z.string(),
  cloneId: z.string(),
});
export const getDiffAgainstRemoteInput = z.object({
  directoryPath: z.string(),
  baseBranch: z.string(),
});

export const getCommitsBetweenBranchesInput = z.object({
  directoryPath: z.string(),
  baseBranch: z.string(),
  head: z.string().optional(),
  limit: z.number(),
});
export const getCommitsBetweenBranchesOutput = z.array(
  z.object({ sha: z.string(), message: z.string() }),
);

export const cloneRepositoryOutput = z.object({ cloneId: z.string() });
export const cloneProgressPayload = z.object({
  cloneId: z.string(),
  status: z.enum(["cloning", "complete", "error"]),
  message: z.string(),
});
export type CloneProgressPayload = z.infer<typeof cloneProgressPayload>;
