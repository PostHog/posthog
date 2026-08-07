import { initTRPC } from "@trpc/server";
import superjson from "superjson";
import { z } from "zod";
import { connectivityStatusOutput } from "./services/connectivity/schemas";
import type { ConnectivityService } from "./services/connectivity/service";
import {
  createEnvironmentInput,
  deleteEnvironmentInput,
  environmentSchema,
  getEnvironmentInput,
  listEnvironmentsInput,
  updateEnvironmentInput,
} from "./services/environment/schemas";
import type { EnvironmentService } from "./services/environment/service";
import {
  checkoutInput,
  findWorktreeInput,
  focusResultSchema,
  focusSessionSchema,
  mainRepoPathInput,
  reattachInput,
  repoPathInput,
  stashInput,
  stashResultSchema,
  syncInput,
  worktreeInput,
} from "./services/focus/schemas";
import type { FocusService } from "./services/focus/service";
import type { FocusSyncService } from "./services/focus/sync-service";
import {
  boundedReadResult,
  listDirectoryInput,
  listDirectoryOutput,
  listRepoFilesInput,
  listRepoFilesOutput,
  readAbsoluteFileInput,
  readRepoFileBoundedInput,
  readRepoFileInput,
  readRepoFileOutput,
  readRepoFilesBoundedInput,
  readRepoFilesBoundedOutput,
  readRepoFilesInput,
  readRepoFilesOutput,
  writeRepoFileInput,
} from "./services/fs/schemas";
import type { FsService } from "./services/fs/service";
import {
  approvePrInput,
  approvePrOutput,
  changedFilesOutput,
  checkoutBranchInput,
  checkoutBranchOutput,
  cleanupAfterCloudHandoffInput,
  cleanupAfterCloudHandoffOutput,
  cloneRepositoryInput,
  cloneRepositoryOutput,
  commitInput,
  commitOutput,
  createBranchInput,
  createPrViaGhInput,
  createPrViaGhOutput,
  detectRepoResultSchema,
  diffInput,
  diffStatsInput,
  diffStatsSchema,
  directoryPathInput,
  discardAllChangesInput,
  discardFileChangesInput,
  discardFileChangesOutput,
  filePathInput,
  getBranchChangedFilesInput,
  getCommitConventionsInput,
  getCommitConventionsOutput,
  getCommitsBetweenBranchesInput,
  getCommitsBetweenBranchesOutput,
  getDiffAgainstRemoteInput,
  getGithubIssueInput,
  getGithubIssueOutput,
  getGithubPullRequestInput,
  getGithubPullRequestOutput,
  getGitSyncStatusInput,
  getHeadShaOutput,
  getLocalBranchChangedFilesInput,
  getPrChangedFilesInput,
  getPrChecksInput,
  getPrChecksOutput,
  getPrCommentsInput,
  getPrCommentsOutput,
  getPrDetailsByUrlInput,
  getPrDetailsByUrlOutput,
  getPrDiffStatsBatchInput,
  getPrDiffStatsBatchOutput,
  getPrInfoByUrlInput,
  getPrInfoByUrlOutput,
  getPrReviewCommentsInput,
  getPrReviewCommentsOutput,
  getPrTemplateInput,
  getPrTemplateOutput,
  getPrUrlForBranchInput,
  getPrUrlForBranchOutput,
  ghAuthTokenOutput,
  ghStatusOutput,
  gitBusyStateInput,
  gitBusyStateSchema,
  gitCommitInfoNullableOutput,
  gitRepoInfoNullableOutput,
  gitStateSnapshotSchema,
  gitStatusOutput,
  syncInput as gitSyncInput,
  syncOutput as gitSyncOutput,
  gitSyncStatusSchema,
  mergePrInput,
  mergePrOutput,
  openPrInput,
  openPrOutput,
  prStatusOutput,
  publishInput,
  publishOutput,
  pullInput,
  pullOutput,
  pushInput,
  pushOutput,
  readHandoffLocalGitStateInput,
  readHandoffLocalGitStateOutput,
  replyToPrCommentInput,
  replyToPrCommentOutput,
  resetSoftInput,
  resolveReviewThreadInput,
  resolveReviewThreadOutput,
  searchGithubRefsInput,
  searchGithubRefsOutput,
  stageFilesInput,
  stringArrayOutput,
  stringNullableOutput,
  stringOutput,
  updatePrByUrlInput,
  updatePrByUrlOutput,
} from "./services/git/schemas";
import type { GitService } from "./services/git/service";
import {
  countLocalLogEntriesInput,
  countLocalLogEntriesOutput,
  deleteLocalLogCacheInput,
  readLocalLogsCollapsedInput,
  readLocalLogsCollapsedOutput,
  readLocalLogsInput,
  readLocalLogsOutput,
  readLocalLogsTailInput,
  readLocalLogsTailOutput,
  seedLocalLogsInput,
  writeLocalLogsInput,
} from "./services/local-logs/schemas";
import type { LocalLogsService } from "./services/local-logs/service";
import {
  resolveGitDirsInput,
  resolveGitDirsOutput,
  watchInput,
  watchRepoInput,
} from "./services/watcher/schemas";
import type { WatcherService } from "./services/watcher/service";

const t = initTRPC.create({ transformer: superjson });

export {
  type FocusBranchRenamedEvent,
  type FocusForeignBranchCheckoutEvent,
  type FocusResult,
  type FocusSession,
  focusBranchRenamedEventSchema,
  focusForeignBranchCheckoutEventSchema,
  focusResultSchema,
  focusSessionSchema,
  type StashResult,
  stashResultSchema,
} from "./services/focus/schemas";
export { type DiffStats, diffStatsSchema } from "./services/git/schemas";
export {
  type FileWatcherEvent,
  FileWatcherEventKind,
} from "./services/watcher/schemas";

export interface WorkspaceServerServices {
  focusService: FocusService;
  focusSyncService: FocusSyncService;
  gitService: GitService;
  fsService: FsService;
  watcherService: WatcherService;
  localLogsService: LocalLogsService;
  connectivityService: ConnectivityService;
  environmentService: EnvironmentService;
}

export function createAppRouter({
  focusService: focusServiceInst,
  focusSyncService: focusSyncServiceInst,
  gitService: gitServiceInst,
  fsService: fsServiceInst,
  watcherService: watcherServiceInst,
  localLogsService: localLogsServiceInst,
  connectivityService: connectivityServiceInst,
  environmentService: environmentServiceInst,
}: WorkspaceServerServices) {
  const focusService = () => focusServiceInst;
  const focusSyncService = () => focusSyncServiceInst;
  const gitService = () => gitServiceInst;
  const fsService = () => fsServiceInst;
  const watcherService = () => watcherServiceInst;
  const localLogsService = () => localLogsServiceInst;
  const connectivityService = () => connectivityServiceInst;
  const environmentService = () => environmentServiceInst;

  return t.router({
    focus: t.router({
      getSession: t.procedure
        .input(mainRepoPathInput)
        .output(focusSessionSchema.nullable())
        .query(({ input }) => focusService().getSession(input.mainRepoPath)),

      saveSession: t.procedure
        .input(focusSessionSchema)
        .mutation(({ input }) => focusService().saveSession(input)),

      deleteSession: t.procedure
        .input(mainRepoPathInput)
        .mutation(({ input }) =>
          focusService().deleteSession(input.mainRepoPath),
        ),

      isFocusActive: t.procedure
        .input(mainRepoPathInput)
        .output(z.boolean())
        .query(({ input }) => focusService().isFocusActive(input.mainRepoPath)),

      isDirty: t.procedure
        .input(repoPathInput)
        .output(z.boolean())
        .query(({ input }) => focusService().isDirty(input.repoPath)),

      getCommitSha: t.procedure
        .input(repoPathInput)
        .output(z.string())
        .query(({ input }) => focusService().getCommitSha(input.repoPath)),

      findWorktreeByBranch: t.procedure
        .input(findWorktreeInput)
        .output(z.string().nullable())
        .query(({ input }) =>
          focusService().findWorktreeByBranch(input.mainRepoPath, input.branch),
        ),

      stash: t.procedure
        .input(stashInput)
        .output(stashResultSchema)
        .mutation(({ input }) =>
          focusService().stash(input.repoPath, input.message),
        ),

      stashPop: t.procedure
        .input(repoPathInput)
        .output(focusResultSchema)
        .mutation(({ input }) => focusService().stashPop(input.repoPath)),

      stashApply: t.procedure
        .input(z.object({ repoPath: z.string(), stashRef: z.string() }))
        .output(focusResultSchema)
        .mutation(({ input }) =>
          focusService().stashApply(input.repoPath, input.stashRef),
        ),

      checkout: t.procedure
        .input(checkoutInput)
        .output(focusResultSchema)
        .mutation(({ input }) =>
          focusService().checkout(input.repoPath, input.branch),
        ),

      detachWorktree: t.procedure
        .input(worktreeInput)
        .output(focusResultSchema)
        .mutation(({ input }) =>
          focusService().detachWorktree(input.worktreePath),
        ),

      reattachWorktree: t.procedure
        .input(reattachInput)
        .output(focusResultSchema)
        .mutation(({ input }) =>
          focusService().reattachWorktree(input.worktreePath, input.branch),
        ),

      cleanWorkingTree: t.procedure
        .input(repoPathInput)
        .mutation(({ input }) =>
          focusService().cleanWorkingTree(input.repoPath),
        ),

      startSync: t.procedure
        .input(syncInput)
        .mutation(({ input }) =>
          focusSyncService().startSync(input.mainRepoPath, input.worktreePath),
        ),

      stopSync: t.procedure.mutation(() => focusSyncService().stopSync()),

      startWatchingMainRepo: t.procedure
        .input(mainRepoPathInput)
        .mutation(({ input }) =>
          focusService().startWatchingMainRepo(input.mainRepoPath),
        ),

      stopWatchingMainRepo: t.procedure.mutation(() =>
        focusService().stopWatchingMainRepo(),
      ),

      onBranchRenamed: t.procedure.subscription(async function* (opts) {
        for await (const event of focusService().branchRenamedEvents(
          opts.signal,
        )) {
          yield event;
        }
      }),

      onForeignBranchCheckout: t.procedure.subscription(async function* (opts) {
        for await (const event of focusService().foreignBranchCheckoutEvents(
          opts.signal,
        )) {
          yield event;
        }
      }),
    }),
    git: t.router({
      detectRepo: t.procedure
        .input(directoryPathInput)
        .output(detectRepoResultSchema)
        .query(({ input }) => gitService().detectRepo(input.directoryPath)),

      validateRepo: t.procedure
        .input(directoryPathInput)
        .output(z.boolean())
        .query(({ input }) => gitService().validateRepo(input.directoryPath)),

      getRemoteUrl: t.procedure
        .input(directoryPathInput)
        .output(stringNullableOutput)
        .query(({ input }) => gitService().getRemoteUrl(input.directoryPath)),

      getCurrentBranch: t.procedure
        .input(directoryPathInput)
        .output(stringNullableOutput)
        .query(({ input, signal }) =>
          gitService().getCurrentBranch(input.directoryPath, signal),
        ),

      getDefaultBranch: t.procedure
        .input(directoryPathInput)
        .output(stringOutput)
        .query(({ input }) =>
          gitService().getDefaultBranch(input.directoryPath),
        ),

      getAllBranches: t.procedure
        .input(directoryPathInput)
        .output(stringArrayOutput)
        .query(({ input, signal }) =>
          gitService().getAllBranches(input.directoryPath, signal),
        ),

      getChangedFilesHead: t.procedure
        .input(directoryPathInput)
        .output(changedFilesOutput)
        .query(({ input, signal }) =>
          gitService().getChangedFilesHead(input.directoryPath, signal),
        ),

      getFileAtHead: t.procedure
        .input(filePathInput)
        .output(stringNullableOutput)
        .query(({ input, signal }) =>
          gitService().getFileAtHead(
            input.directoryPath,
            input.filePath,
            signal,
          ),
        ),

      getDiffHead: t.procedure
        .input(diffInput)
        .output(stringOutput)
        .query(({ input, signal }) =>
          gitService().getDiffHead(
            input.directoryPath,
            input.ignoreWhitespace,
            signal,
          ),
        ),

      getDiffCached: t.procedure
        .input(diffInput)
        .output(stringOutput)
        .query(({ input, signal }) =>
          gitService().getDiffCached(
            input.directoryPath,
            input.ignoreWhitespace,
            signal,
          ),
        ),

      getDiffUnstaged: t.procedure
        .input(diffInput)
        .output(stringOutput)
        .query(({ input, signal }) =>
          gitService().getDiffUnstaged(
            input.directoryPath,
            input.ignoreWhitespace,
            signal,
          ),
        ),

      getLatestCommit: t.procedure
        .input(directoryPathInput)
        .output(gitCommitInfoNullableOutput)
        .query(({ input, signal }) =>
          gitService().getLatestCommit(input.directoryPath, signal),
        ),

      getGitRepoInfo: t.procedure
        .input(directoryPathInput)
        .output(gitRepoInfoNullableOutput)
        .query(({ input }) => gitService().getGitRepoInfo(input.directoryPath)),

      getGitBusyState: t.procedure
        .input(gitBusyStateInput)
        .output(gitBusyStateSchema)
        .query(({ input, signal }) =>
          gitService().getGitBusyState(input.directoryPath, signal),
        ),

      getGitSyncStatus: t.procedure
        .input(getGitSyncStatusInput)
        .output(gitSyncStatusSchema)
        .query(({ input }) =>
          gitService().getGitSyncStatus(
            input.directoryPath,
            input.fetchFromRemote,
          ),
        ),

      createBranch: t.procedure
        .input(createBranchInput)
        .mutation(({ input }) =>
          gitService().createBranch(input.directoryPath, input.branchName),
        ),

      checkoutBranch: t.procedure
        .input(checkoutBranchInput)
        .output(checkoutBranchOutput)
        .mutation(({ input }) =>
          gitService().checkoutBranch(input.directoryPath, input.branchName),
        ),

      stageFiles: t.procedure
        .input(stageFilesInput)
        .output(gitStateSnapshotSchema)
        .mutation(({ input }) =>
          gitService().stageFiles(input.directoryPath, input.paths),
        ),

      unstageFiles: t.procedure
        .input(stageFilesInput)
        .output(gitStateSnapshotSchema)
        .mutation(({ input }) =>
          gitService().unstageFiles(input.directoryPath, input.paths),
        ),

      discardFileChanges: t.procedure
        .input(discardFileChangesInput)
        .output(discardFileChangesOutput)
        .mutation(({ input }) =>
          gitService().discardFileChanges(
            input.directoryPath,
            input.filePath,
            input.fileStatus,
          ),
        ),

      discardAllChanges: t.procedure
        .input(discardAllChangesInput)
        .output(discardFileChangesOutput)
        .mutation(({ input }) =>
          gitService().discardAllChanges(input.directoryPath),
        ),

      push: t.procedure
        .input(pushInput)
        .output(pushOutput)
        .mutation(({ input, signal }) =>
          gitService().push(
            input.directoryPath,
            input.remote,
            input.branch,
            input.setUpstream,
            signal,
            input.env,
          ),
        ),

      commit: t.procedure
        .input(commitInput)
        .output(commitOutput)
        .mutation(({ input }) =>
          gitService().commit(input.directoryPath, input.message, {
            paths: input.paths,
            allowEmpty: input.allowEmpty,
            stagedOnly: input.stagedOnly,
            env: input.env,
          }),
        ),

      pull: t.procedure
        .input(pullInput)
        .output(pullOutput)
        .mutation(({ input, signal }) =>
          gitService().pull(
            input.directoryPath,
            input.remote,
            input.branch,
            signal,
          ),
        ),

      publish: t.procedure
        .input(publishInput)
        .output(publishOutput)
        .mutation(({ input, signal }) =>
          gitService().publish(
            input.directoryPath,
            input.remote,
            signal,
            input.env,
          ),
        ),

      sync: t.procedure
        .input(gitSyncInput)
        .output(gitSyncOutput)
        .mutation(({ input, signal }) =>
          gitService().sync(input.directoryPath, input.remote, signal),
        ),

      getGhStatus: t.procedure
        .output(ghStatusOutput)
        .query(() => gitService().getGhStatus()),

      getGhAuthToken: t.procedure
        .output(ghAuthTokenOutput)
        .query(() => gitService().getGhAuthToken()),

      getPrStatus: t.procedure
        .input(directoryPathInput)
        .output(prStatusOutput)
        .query(({ input }) => gitService().getPrStatus(input.directoryPath)),

      getPrUrlForBranch: t.procedure
        .input(getPrUrlForBranchInput)
        .output(getPrUrlForBranchOutput)
        .query(({ input }) =>
          gitService().getPrUrlForBranch(input.directoryPath, input.branchName),
        ),

      openPr: t.procedure
        .input(openPrInput)
        .output(openPrOutput)
        .mutation(({ input }) => gitService().openPr(input.directoryPath)),

      getPrDetailsByUrl: t.procedure
        .input(getPrDetailsByUrlInput)
        .output(getPrDetailsByUrlOutput.nullable())
        .query(({ input }) => gitService().getPrDetailsByUrl(input.prUrl)),

      getPrInfoByUrl: t.procedure
        .input(getPrInfoByUrlInput)
        .output(getPrInfoByUrlOutput.nullable())
        .query(({ input }) => gitService().getPrInfoByUrl(input.prUrl)),

      getPrChecks: t.procedure
        .input(getPrChecksInput)
        .output(getPrChecksOutput)
        .query(({ input }) => gitService().getPrChecks(input.prUrl)),

      getPrComments: t.procedure
        .input(getPrCommentsInput)
        .output(getPrCommentsOutput)
        .query(({ input }) => gitService().getPrComments(input.prUrl)),

      getPrChangedFiles: t.procedure
        .input(getPrChangedFilesInput)
        .output(changedFilesOutput)
        .query(({ input }) => gitService().getPrChangedFiles(input.prUrl)),

      getPrDiffStatsBatch: t.procedure
        .input(getPrDiffStatsBatchInput)
        .output(getPrDiffStatsBatchOutput)
        .query(({ input }) => gitService().getPrDiffStatsBatch(input.prUrls)),

      getBranchChangedFiles: t.procedure
        .input(getBranchChangedFilesInput)
        .output(changedFilesOutput)
        .query(({ input }) =>
          gitService().getBranchChangedFiles(input.repo, input.branch),
        ),

      getLocalBranchChangedFiles: t.procedure
        .input(getLocalBranchChangedFilesInput)
        .output(changedFilesOutput)
        .query(({ input }) =>
          gitService().getLocalBranchChangedFiles(
            input.directoryPath,
            input.branch,
          ),
        ),

      updatePrByUrl: t.procedure
        .input(updatePrByUrlInput)
        .output(updatePrByUrlOutput)
        .mutation(({ input }) =>
          gitService().updatePrByUrl(input.prUrl, input.action),
        ),

      approvePr: t.procedure
        .input(approvePrInput)
        .output(approvePrOutput)
        .mutation(({ input }) => gitService().approvePr(input.prUrl)),

      mergePr: t.procedure
        .input(mergePrInput)
        .output(mergePrOutput)
        .mutation(({ input }) =>
          gitService().mergePr(input.prUrl, input.method),
        ),

      getPrReviewComments: t.procedure
        .input(getPrReviewCommentsInput)
        .output(getPrReviewCommentsOutput)
        .query(({ input }) => gitService().getPrReviewComments(input.prUrl)),

      resolveReviewThread: t.procedure
        .input(resolveReviewThreadInput)
        .output(resolveReviewThreadOutput)
        .mutation(({ input }) =>
          gitService().resolveReviewThread(input.threadNodeId, input.resolved),
        ),

      replyToPrComment: t.procedure
        .input(replyToPrCommentInput)
        .output(replyToPrCommentOutput)
        .mutation(({ input }) =>
          gitService().replyToPrComment(
            input.prUrl,
            input.commentId,
            input.body,
          ),
        ),

      getPrTemplate: t.procedure
        .input(getPrTemplateInput)
        .output(getPrTemplateOutput)
        .query(({ input }) => gitService().getPrTemplate(input.directoryPath)),

      getCommitConventions: t.procedure
        .input(getCommitConventionsInput)
        .output(getCommitConventionsOutput)
        .query(({ input }) =>
          gitService().getCommitConventions(
            input.directoryPath,
            input.sampleSize,
          ),
        ),

      searchGithubRefs: t.procedure
        .input(searchGithubRefsInput)
        .output(searchGithubRefsOutput)
        .query(({ input }) =>
          gitService().searchGithubRefs(
            input.directoryPath,
            input.query,
            input.limit,
            input.kinds,
          ),
        ),

      getGithubIssue: t.procedure
        .input(getGithubIssueInput)
        .output(getGithubIssueOutput)
        .query(({ input }) =>
          gitService().getGithubIssue(input.owner, input.repo, input.number),
        ),

      getGithubPullRequest: t.procedure
        .input(getGithubPullRequestInput)
        .output(getGithubPullRequestOutput)
        .query(({ input }) =>
          gitService().getGithubPullRequest(
            input.owner,
            input.repo,
            input.number,
          ),
        ),

      readHandoffLocalGitState: t.procedure
        .input(readHandoffLocalGitStateInput)
        .output(readHandoffLocalGitStateOutput)
        .query(({ input }) =>
          gitService().readHandoffLocalGitState(input.directoryPath),
        ),

      cleanupAfterCloudHandoff: t.procedure
        .input(cleanupAfterCloudHandoffInput)
        .output(cleanupAfterCloudHandoffOutput)
        .mutation(({ input }) =>
          gitService().cleanupAfterCloudHandoff(
            input.directoryPath,
            input.branchName,
          ),
        ),

      getDiffStats: t.procedure
        .input(diffStatsInput)
        .output(diffStatsSchema)
        .query(({ input }) => gitService().getDiffStats(input.directoryPath)),

      getGitStatus: t.procedure
        .output(gitStatusOutput)
        .query(() => gitService().getGitStatus()),

      getHeadSha: t.procedure
        .input(directoryPathInput)
        .output(getHeadShaOutput)
        .query(({ input }) => gitService().getHeadSha(input.directoryPath)),

      getDiffAgainstRemote: t.procedure
        .input(getDiffAgainstRemoteInput)
        .output(stringOutput)
        .query(({ input }) =>
          gitService().getDiffAgainstRemote(
            input.directoryPath,
            input.baseBranch,
          ),
        ),

      getCommitsBetweenBranches: t.procedure
        .input(getCommitsBetweenBranchesInput)
        .output(getCommitsBetweenBranchesOutput)
        .query(({ input }) =>
          gitService().getCommitsBetweenBranches(
            input.directoryPath,
            input.baseBranch,
            input.head,
            input.limit,
          ),
        ),

      resetSoft: t.procedure
        .input(resetSoftInput)
        .mutation(({ input }) =>
          gitService().resetSoft(input.directoryPath, input.sha),
        ),

      createPrViaGh: t.procedure
        .input(createPrViaGhInput)
        .output(createPrViaGhOutput)
        .mutation(({ input }) =>
          gitService().createPrViaGh(
            input.directoryPath,
            input.title,
            input.body,
            input.draft,
            input.env,
          ),
        ),

      cloneRepository: t.procedure
        .input(cloneRepositoryInput)
        .output(cloneRepositoryOutput)
        .mutation(({ input }) =>
          gitService().cloneRepository(
            input.repoUrl,
            input.targetPath,
            input.cloneId,
          ),
        ),

      onCloneProgress: t.procedure.subscription(async function* (opts) {
        for await (const data of gitService().toIterable("cloneProgress", {
          signal: opts.signal,
        })) {
          yield data;
        }
      }),
    }),
    fs: t.router({
      listDirectory: t.procedure
        .input(listDirectoryInput)
        .output(listDirectoryOutput)
        .query(({ input }) => fsService().listDirectory(input.dirPath)),

      listRepoFiles: t.procedure
        .input(listRepoFilesInput)
        .output(listRepoFilesOutput)
        .query(({ input }) =>
          fsService().listRepoFiles(input.repoPath, input.query, input.limit),
        ),

      readRepoFile: t.procedure
        .input(readRepoFileInput)
        .output(readRepoFileOutput)
        .query(({ input }) =>
          fsService().readRepoFile(input.repoPath, input.filePath),
        ),

      readRepoFiles: t.procedure
        .input(readRepoFilesInput)
        .output(readRepoFilesOutput)
        .query(({ input }) =>
          fsService().readRepoFiles(input.repoPath, input.filePaths),
        ),

      readRepoFileBounded: t.procedure
        .input(readRepoFileBoundedInput)
        .output(boundedReadResult)
        .query(({ input }) =>
          fsService().readRepoFileBounded(
            input.repoPath,
            input.filePath,
            input.maxLines,
          ),
        ),

      readRepoFilesBounded: t.procedure
        .input(readRepoFilesBoundedInput)
        .output(readRepoFilesBoundedOutput)
        .query(({ input }) =>
          fsService().readRepoFilesBounded(
            input.repoPath,
            input.filePaths,
            input.maxLines,
          ),
        ),

      readAbsoluteFile: t.procedure
        .input(readAbsoluteFileInput)
        .output(readRepoFileOutput)
        .query(({ input }) => fsService().readAbsoluteFile(input.filePath)),

      readFileAsBase64: t.procedure
        .input(readAbsoluteFileInput)
        .output(readRepoFileOutput)
        .query(({ input }) => fsService().readFileAsBase64(input.filePath)),

      writeRepoFile: t.procedure
        .input(writeRepoFileInput)
        .mutation(({ input }) =>
          fsService().writeRepoFile(
            input.repoPath,
            input.filePath,
            input.content,
          ),
        ),
    }),
    watcher: t.router({
      resolveGitDirs: t.procedure
        .input(resolveGitDirsInput)
        .output(resolveGitDirsOutput)
        .query(({ input }) => watcherService().resolveGitDirs(input.repoPath)),

      watch: t.procedure
        .input(watchInput)
        .subscription(({ input, signal }) =>
          watcherService().watch(
            input.dirPath,
            { ignore: input.ignore },
            signal,
          ),
        ),
    }),
    fileWatcher: t.router({
      watch: t.procedure
        .input(watchRepoInput)
        .subscription(({ input, signal }) =>
          watcherService().watchRepo(input.repoPath, signal),
        ),
    }),
    localLogs: t.router({
      read: t.procedure
        .input(readLocalLogsInput)
        .output(readLocalLogsOutput)
        .query(({ input }) =>
          localLogsService().readLocalLogs(input.taskRunId),
        ),

      readCollapsed: t.procedure
        .input(readLocalLogsCollapsedInput)
        .output(readLocalLogsCollapsedOutput)
        .query(({ input }) =>
          localLogsService().readLocalLogsCollapsed(input.taskRunId),
        ),

      readTail: t.procedure
        .input(readLocalLogsTailInput)
        .output(readLocalLogsTailOutput)
        .query(({ input }) =>
          localLogsService().readLocalLogsTail(input.taskRunId, input.maxBytes),
        ),

      write: t.procedure
        .input(writeLocalLogsInput)
        .mutation(({ input }) =>
          localLogsService().writeLocalLogs(input.taskRunId, input.content),
        ),

      seed: t.procedure
        .input(seedLocalLogsInput)
        .mutation(({ input }) =>
          localLogsService().seedLocalLogs(input.taskRunId, input.content),
        ),

      count: t.procedure
        .input(countLocalLogEntriesInput)
        .output(countLocalLogEntriesOutput)
        .query(({ input }) =>
          localLogsService().countLocalLogEntries(input.taskRunId),
        ),

      delete: t.procedure
        .input(deleteLocalLogCacheInput)
        .mutation(({ input }) =>
          localLogsService().deleteLocalLogCache(input.taskRunId),
        ),
    }),
    connectivity: t.router({
      getStatus: t.procedure
        .output(connectivityStatusOutput)
        .query(() => connectivityService().getStatus()),

      checkNow: t.procedure
        .output(connectivityStatusOutput)
        .mutation(() => connectivityService().checkNow()),

      onStatusChange: t.procedure.subscription(async function* (opts) {
        for await (const status of connectivityService().statusChangeEvents(
          opts.signal,
        )) {
          yield status;
        }
      }),
    }),
    environment: t.router({
      list: t.procedure
        .input(listEnvironmentsInput)
        .output(environmentSchema.array())
        .query(({ input }) =>
          environmentService().listEnvironments(input.repoPath),
        ),

      get: t.procedure
        .input(getEnvironmentInput)
        .output(environmentSchema.nullable())
        .query(({ input }) =>
          environmentService().getEnvironment(input.repoPath, input.id),
        ),

      create: t.procedure
        .input(createEnvironmentInput)
        .output(environmentSchema)
        .mutation(({ input }) => {
          const { repoPath, ...rest } = input;
          return environmentService().createEnvironment(rest, repoPath);
        }),

      update: t.procedure
        .input(updateEnvironmentInput)
        .output(environmentSchema)
        .mutation(({ input }) => {
          const { repoPath, ...rest } = input;
          return environmentService().updateEnvironment(rest, repoPath);
        }),

      delete: t.procedure
        .input(deleteEnvironmentInput)
        .mutation(({ input }) =>
          environmentService().deleteEnvironment(input.repoPath, input.id),
        ),
    }),
  });
}

export type AppRouter = ReturnType<typeof createAppRouter>;
