import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { execGh } from "@posthog/git/gh";
import { readHandoffLocalGitState } from "@posthog/git/handoff";
import { getGitOperationManager } from "@posthog/git/operation-manager";
import {
  type DiffStats,
  type GitBusyState,
  getAllBranches,
  getBranchDiffPatchesByPath,
  getChangedFilesBetweenBranches,
  getChangedFilesDetailed,
  getCommitConventions,
  getCommitsBetweenBranches,
  getCurrentBranch,
  getDefaultBranch,
  getDiffAgainstRemote,
  getDiffHead,
  getDiffStats,
  getFileAtHead,
  getGitBusyState,
  getHeadSha,
  getLatestCommit,
  getRemoteUrl,
  getStagedDiff,
  getSyncStatus,
  getUnstagedDiff,
  fetch as gitFetch,
  stageFiles as gitStageFiles,
  unstageFiles as gitUnstageFiles,
  isGitRepository,
} from "@posthog/git/queries";
import {
  CreateBranchSaga,
  ResetToDefaultBranchSaga,
  SwitchBranchSaga,
} from "@posthog/git/sagas/branch";
import { CleanWorkingTreeSaga } from "@posthog/git/sagas/clean";
import { CloneSaga } from "@posthog/git/sagas/clone";
import { CommitSaga } from "@posthog/git/sagas/commit";
import { DiscardFileChangesSaga } from "@posthog/git/sagas/discard";
import { PullSaga } from "@posthog/git/sagas/pull";
import { PushSaga } from "@posthog/git/sagas/push";
import { StashPushSaga } from "@posthog/git/sagas/stash";
import { parseGithubUrl } from "@posthog/git/utils";
import { TypedEventEmitter } from "@posthog/shared";
import { injectable } from "inversify";
import type { SidebarPrState } from "../workspace/schemas";
import type {
  ApprovePrOutput,
  ChangedFile,
  CloneProgressPayload,
  CommitOutput,
  DetectRepoResult,
  DiscardFileChangesOutput,
  GetCommitConventionsOutput,
  GetPrChecksOutput,
  GetPrCommentsOutput,
  GetPrTemplateOutput,
  GhAuthTokenOutput,
  GhStatusOutput,
  GitCommitInfo,
  GitFileStatus,
  GithubRef,
  GithubRefKind,
  GitRepoInfo,
  GitStateSnapshot,
  GitStatusOutput,
  GitSyncStatus,
  HandoffLocalGitState,
  MergePrOutput,
  OpenPrOutput,
  PrActionType,
  PrCheck,
  PrCheckBucket,
  PrConversationComment,
  PrDetailsByUrlOutput,
  PrDiffStats,
  PrInfoByUrlOutput,
  PrMergeMethod,
  PrReviewComment,
  PrReviewThread,
  PrStatusOutput,
  PublishOutput,
  PullOutput,
  PushOutput,
  ReplyToPrCommentOutput,
  ResolveReviewThreadOutput,
  SyncOutput,
  UpdatePrByUrlOutput,
} from "./schemas";
import { getPrInfoByUrlOutput, prConversationCommentSchema } from "./schemas";

const FETCH_THROTTLE_MS = 30_000;
/** Max PRs per GraphQL request – stays well under GitHub's complexity ceiling. */
const PR_DIFF_STATS_BATCH_CHUNK_SIZE = 25;

/**
 * Escape a string for embedding in a GraphQL double-quoted literal. GitHub
 * repo names already conform to a safe subset, but defense-in-depth so a
 * pathological owner/repo can never break out of the query envelope.
 */
function escapeGraphqlString(value: string): string {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/\n/g, "\\n")
    .replace(/\r/g, "\\r")
    .replace(/\t/g, "\\t");
}

/**
 * GitHub's compare/files API returns a bare hunk body. Reconstruct a full
 * unified-diff patch (with `diff --git` + `---`/`+++` headers) so downstream
 * parsers can process it correctly.
 */
function toUnifiedDiffPatch(
  rawPatch: string,
  filename: string,
  previousFilename: string | undefined,
  status: ChangedFile["status"],
): string {
  const oldPath = previousFilename ?? filename;
  const fromPath = status === "added" ? "/dev/null" : `a/${oldPath}`;
  const toPath = status === "deleted" ? "/dev/null" : `b/${filename}`;
  return `diff --git a/${oldPath} b/${filename}\n--- ${fromPath}\n+++ ${toPath}\n${rawPatch}`;
}

/**
 * Narrow GitHub GraphQL's `PullRequestState` (OPEN | CLOSED | MERGED) to the
 * lowercased literal the batch schema expects. Anything unexpected falls back
 * to "open" so one odd value can never fail validation for the whole batch.
 */
function normalizeGraphqlPrState(
  graphqlState: string,
): "open" | "closed" | "merged" {
  switch (graphqlState) {
    case "MERGED":
      return "merged";
    case "CLOSED":
      return "closed";
    default:
      return "open";
  }
}

/**
 * Narrow `gh pr checks` bucket values to the schema enum. Unknown values fall
 * back to "pending" so one odd bucket can never fail the whole checks list.
 */
function normalizeCheckBucket(bucket: string | undefined): PrCheckBucket {
  switch (bucket) {
    case "fail":
    case "cancel":
    case "pass":
    case "skipping":
      return bucket;
    default:
      return "pending";
  }
}

export function mapPrState(
  state: string | null,
  merged: boolean,
  draft: boolean,
): SidebarPrState {
  const lower = state?.toLowerCase() ?? null;
  if (merged || lower === "merged") return "merged";
  if (lower === "closed") return "closed";
  if (draft) return "draft";
  if (lower === "open") return "open";
  return null;
}

export const GitCloneEvent = { CloneProgress: "cloneProgress" } as const;
export interface GitCloneEvents {
  [GitCloneEvent.CloneProgress]: CloneProgressPayload;
}

const execFileAsync = promisify(execFile);

@injectable()
export class GitService extends TypedEventEmitter<GitCloneEvents> {
  async getDiffStats(directoryPath: string): Promise<DiffStats> {
    return getDiffStats(directoryPath);
  }

  async getHeadSha(directoryPath: string): Promise<string> {
    return getHeadSha(directoryPath);
  }

  async getDiffAgainstRemote(
    directoryPath: string,
    baseBranch: string,
  ): Promise<string> {
    return getDiffAgainstRemote(directoryPath, baseBranch);
  }

  async getCommitsBetweenBranches(
    directoryPath: string,
    baseBranch: string,
    head: string | undefined,
    limit: number,
  ): Promise<Array<{ sha: string; message: string }>> {
    return getCommitsBetweenBranches(directoryPath, baseBranch, head, limit);
  }

  async resetSoft(directoryPath: string, sha: string): Promise<void> {
    await getGitOperationManager().executeWrite(directoryPath, (git) =>
      git.reset(["--soft", sha]),
    );
  }

  async getGitStatus(): Promise<GitStatusOutput> {
    try {
      const { stdout } = await execFileAsync("git", ["--version"]);
      return { installed: true, version: stdout.trim() };
    } catch {
      return { installed: false, version: null };
    }
  }

  async createPrViaGh(
    directoryPath: string,
    title?: string,
    body?: string,
    draft?: boolean,
    env?: Record<string, string>,
  ): Promise<{ success: boolean; message: string; prUrl: string | null }> {
    const prFooter =
      "\n\n---\n*Created with [PostHog Code](https://posthog.com/code?ref=pr)*";
    const args = ["pr", "create"];
    if (title) {
      args.push("--title", title);
      args.push("--body", (body || "") + prFooter);
    } else {
      args.push("--fill");
    }
    if (draft) args.push("--draft");

    const result = await execGh(args, { cwd: directoryPath, env });
    if (result.exitCode !== 0) {
      return {
        success: false,
        message: result.stderr || result.error || "Failed to create PR",
        prUrl: null,
      };
    }
    const prUrl =
      result.stdout.match(/https:\/\/github\.com\/[^\s]+/)?.[0] ?? null;
    return { success: true, message: "Pull request created", prUrl };
  }

  async cloneRepository(
    repoUrl: string,
    targetPath: string,
    cloneId: string,
  ): Promise<{ cloneId: string }> {
    const emit = (
      status: CloneProgressPayload["status"],
      message: string,
    ): void => {
      this.emit(GitCloneEvent.CloneProgress, { cloneId, status, message });
    };

    emit("cloning", `Starting clone of ${repoUrl}...`);
    const result = await new CloneSaga().run({
      repoUrl,
      targetPath,
      onProgress: (stage, progress, processed, total) => {
        const pct = progress ? ` ${Math.round(progress)}%` : "";
        const count = total ? ` (${processed}/${total})` : "";
        emit("cloning", `${stage}${pct}${count}`);
      },
    });
    if (!result.success) {
      emit("error", result.error);
      throw new Error(result.error);
    }
    emit("complete", "Clone completed successfully");
    return { cloneId };
  }

  async detectRepo(directoryPath: string): Promise<DetectRepoResult> {
    if (!directoryPath) return null;

    const remoteUrl = await getRemoteUrl(directoryPath);
    if (!remoteUrl) return null;

    const parsed = parseGithubUrl(remoteUrl);
    if (!parsed) return null;

    const branch = await getCurrentBranch(directoryPath);
    if (!branch) return null;

    return {
      organization: parsed.owner,
      repository: parsed.repo,
      remote: remoteUrl,
      branch,
    };
  }

  async validateRepo(directoryPath: string): Promise<boolean> {
    if (!directoryPath) return false;
    return isGitRepository(directoryPath);
  }

  async getRemoteUrl(directoryPath: string): Promise<string | null> {
    return getRemoteUrl(directoryPath);
  }

  async getCurrentBranch(
    directoryPath: string,
    signal?: AbortSignal,
  ): Promise<string | null> {
    return getCurrentBranch(directoryPath, { abortSignal: signal });
  }

  async getDefaultBranch(directoryPath: string): Promise<string> {
    return getDefaultBranch(directoryPath);
  }

  async getAllBranches(
    directoryPath: string,
    signal?: AbortSignal,
  ): Promise<string[]> {
    return getAllBranches(directoryPath, { abortSignal: signal });
  }

  async getChangedFilesHead(
    directoryPath: string,
    signal?: AbortSignal,
  ): Promise<ChangedFile[]> {
    const files = await getChangedFilesDetailed(directoryPath, {
      excludePatterns: [".claude", "CLAUDE.local.md"],
      abortSignal: signal,
    });
    type HeadChangedFile = Omit<ChangedFile, "patch">;
    const filteredFiles: Array<HeadChangedFile | null> = await Promise.all(
      files.map(async (file) => {
        if (file.status === "untracked") {
          try {
            const stats = await fs.promises.stat(
              path.join(directoryPath, file.path),
            );
            if (!stats.isFile()) return null;
          } catch {
            return null;
          }
        }

        return {
          path: file.path,
          status: file.status,
          originalPath: file.originalPath,
          linesAdded: file.linesAdded,
          linesRemoved: file.linesRemoved,
          staged: file.staged,
        };
      }),
    );

    return filteredFiles.filter(
      (file): file is HeadChangedFile => file !== null,
    );
  }

  async getFileAtHead(
    directoryPath: string,
    filePath: string,
    signal?: AbortSignal,
  ): Promise<string | null> {
    return getFileAtHead(directoryPath, filePath, { abortSignal: signal });
  }

  async getDiffHead(
    directoryPath: string,
    ignoreWhitespace?: boolean,
    signal?: AbortSignal,
  ): Promise<string> {
    return getDiffHead(directoryPath, {
      ignoreWhitespace,
      abortSignal: signal,
    });
  }

  async getDiffCached(
    directoryPath: string,
    ignoreWhitespace?: boolean,
    signal?: AbortSignal,
  ): Promise<string> {
    return getStagedDiff(directoryPath, {
      ignoreWhitespace,
      abortSignal: signal,
    });
  }

  async getDiffUnstaged(
    directoryPath: string,
    ignoreWhitespace?: boolean,
    signal?: AbortSignal,
  ): Promise<string> {
    return getUnstagedDiff(directoryPath, {
      ignoreWhitespace,
      abortSignal: signal,
    });
  }

  async getLatestCommit(
    directoryPath: string,
    signal?: AbortSignal,
  ): Promise<GitCommitInfo | null> {
    const commit = await getLatestCommit(directoryPath, {
      abortSignal: signal,
    });
    if (!commit) return null;
    return {
      sha: commit.sha,
      shortSha: commit.shortSha,
      message: commit.message,
      author: commit.author,
      date: commit.date,
    };
  }

  async getGitRepoInfo(directoryPath: string): Promise<GitRepoInfo | null> {
    try {
      const remoteUrl = await getRemoteUrl(directoryPath);
      if (!remoteUrl) return null;

      const parsed = parseGithubUrl(remoteUrl);
      if (!parsed) return null;

      const currentBranch = await getCurrentBranch(directoryPath);
      const defaultBranch = await getDefaultBranch(directoryPath);

      let compareUrl: string | null = null;
      if (currentBranch && currentBranch !== defaultBranch) {
        compareUrl = `https://github.com/${parsed.owner}/${parsed.repo}/compare/${defaultBranch}...${currentBranch}?expand=1`;
      }

      return {
        organization: parsed.owner,
        repository: parsed.repo,
        currentBranch: currentBranch ?? null,
        defaultBranch,
        compareUrl,
      };
    } catch {
      return null;
    }
  }

  // --- git-mutate group ---

  private readonly lastFetchTime = new Map<string, number>();

  /**
   * Always runs `git fetch`, bypassing the staleness throttle. Use when the
   * caller has explicitly asked for a fresh view of the remote (e.g.,
   * `fetchFromRemote: true`) — otherwise a fetch triggered by a preceding
   * mutation can silently swallow this one and leave the snapshot stale at
   * exactly the moment it mattered.
   */
  private async forceFetch(directoryPath: string): Promise<void> {
    try {
      await gitFetch(directoryPath);
      this.lastFetchTime.set(directoryPath, Date.now());
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      process.stderr.write(
        `[git-service] fetch failed for ${directoryPath}; using local refs: ${message}\n`,
      );
    }
  }

  private async fetchIfStale(directoryPath: string): Promise<void> {
    const now = Date.now();
    const lastFetch = this.lastFetchTime.get(directoryPath) ?? 0;
    if (now - lastFetch > FETCH_THROTTLE_MS) {
      await this.forceFetch(directoryPath);
    }
  }

  private async getGitSyncStatusInternal(
    directoryPath: string,
    fetchFromRemote = false,
  ): Promise<GitSyncStatus> {
    if (fetchFromRemote) {
      await this.forceFetch(directoryPath);
    }

    const status = await getSyncStatus(directoryPath);
    return {
      aheadOfRemote: status.aheadOfRemote,
      behind: status.behind,
      aheadOfDefault: status.aheadOfDefault,
      hasRemote: status.hasRemote,
      currentBranch: status.currentBranch,
      isFeatureBranch: status.isFeatureBranch,
    };
  }

  private async getStateSnapshot(
    directoryPath: string,
    options?: {
      includeChangedFiles?: boolean;
      includeDiffStats?: boolean;
      includeSyncStatus?: boolean;
      includeLatestCommit?: boolean;
    },
  ): Promise<GitStateSnapshot> {
    const {
      includeChangedFiles = true,
      includeDiffStats = true,
      includeSyncStatus = true,
      includeLatestCommit = true,
    } = options ?? {};

    const results = await Promise.allSettled([
      includeChangedFiles ? this.getChangedFilesHead(directoryPath) : null,
      includeDiffStats ? this.getDiffStats(directoryPath) : null,
      includeSyncStatus
        ? this.getGitSyncStatusInternal(directoryPath, false)
        : null,
      includeLatestCommit ? this.getLatestCommit(directoryPath) : null,
    ]);

    const getValue = <T>(r: PromiseSettledResult<T | null>): T | undefined =>
      r.status === "fulfilled" && r.value !== null ? r.value : undefined;

    return {
      changedFiles: getValue(results[0]),
      diffStats: getValue(results[1]),
      syncStatus: getValue(results[2]),
      latestCommit: getValue(results[3]),
    };
  }

  async getGitBusyState(
    directoryPath: string,
    signal?: AbortSignal,
  ): Promise<GitBusyState> {
    return getGitBusyState(directoryPath, { abortSignal: signal });
  }

  async getGitSyncStatus(
    directoryPath: string,
    fetchFromRemote = false,
  ): Promise<GitSyncStatus> {
    return this.getGitSyncStatusInternal(directoryPath, fetchFromRemote);
  }

  async createBranch(directoryPath: string, branchName: string): Promise<void> {
    const saga = new CreateBranchSaga();
    const result = await saga.run({ baseDir: directoryPath, branchName });
    if (!result.success) throw new Error(result.error);
  }

  async checkoutBranch(
    directoryPath: string,
    branchName: string,
  ): Promise<{ previousBranch: string; currentBranch: string }> {
    const saga = new SwitchBranchSaga();
    const result = await saga.run({ baseDir: directoryPath, branchName });
    if (!result.success) throw new Error(result.error);
    return result.data;
  }

  async stageFiles(
    directoryPath: string,
    paths: string[],
  ): Promise<GitStateSnapshot> {
    await gitStageFiles(directoryPath, paths);
    return this.getStateSnapshot(directoryPath);
  }

  async unstageFiles(
    directoryPath: string,
    paths: string[],
  ): Promise<GitStateSnapshot> {
    await gitUnstageFiles(directoryPath, paths);
    return this.getStateSnapshot(directoryPath);
  }

  async discardFileChanges(
    directoryPath: string,
    filePath: string,
    fileStatus: GitFileStatus,
  ): Promise<DiscardFileChangesOutput> {
    const saga = new DiscardFileChangesSaga();
    const result = await saga.run({
      baseDir: directoryPath,
      filePath,
      fileStatus,
    });
    if (!result.success) {
      return { success: false };
    }

    const state = await this.getStateSnapshot(directoryPath, {
      includeSyncStatus: false,
      includeLatestCommit: false,
    });

    return { success: true, state };
  }

  async discardAllChanges(
    directoryPath: string,
  ): Promise<DiscardFileChangesOutput> {
    const saga = new CleanWorkingTreeSaga();
    const result = await saga.run({ baseDir: directoryPath });
    if (!result.success) {
      return { success: false };
    }

    const state = await this.getStateSnapshot(directoryPath, {
      includeSyncStatus: false,
      includeLatestCommit: false,
    });

    return { success: true, state };
  }

  async push(
    directoryPath: string,
    remote = "origin",
    branch?: string,
    setUpstream = false,
    signal?: AbortSignal,
    env?: Record<string, string>,
  ): Promise<PushOutput> {
    const saga = new PushSaga();
    const result = await saga.run({
      baseDir: directoryPath,
      remote,
      branch: branch || undefined,
      setUpstream,
      signal,
      env,
    });
    if (!result.success) {
      return { success: false, message: result.error };
    }

    const state = await this.getStateSnapshot(directoryPath, {
      includeChangedFiles: false,
      includeDiffStats: false,
      includeLatestCommit: false,
    });

    return {
      success: true,
      message: `Pushed ${result.data.branch} to ${result.data.remote}`,
      state,
    };
  }

  async commit(
    directoryPath: string,
    message: string,
    options?: {
      paths?: string[];
      allowEmpty?: boolean;
      stagedOnly?: boolean;
      env?: Record<string, string>;
    },
  ): Promise<CommitOutput> {
    const fail = (msg: string): CommitOutput => ({
      success: false,
      message: msg,
      commitSha: null,
      branch: null,
    });

    if (!message.trim()) return fail("Commit message is required");

    const saga = new CommitSaga();
    const result = await saga.run({
      baseDir: directoryPath,
      message: message.trim(),
      paths: options?.paths,
      allowEmpty: options?.allowEmpty,
      stagedOnly: options?.stagedOnly,
      env: options?.env,
    });

    if (!result.success) return fail(result.error);

    const state = await this.getStateSnapshot(directoryPath);

    return {
      success: true,
      message: `Committed ${result.data.commitSha.slice(0, 7)}`,
      commitSha: result.data.commitSha,
      branch: result.data.branch,
      state,
    };
  }

  async pull(
    directoryPath: string,
    remote = "origin",
    branch?: string,
    signal?: AbortSignal,
  ): Promise<PullOutput> {
    const saga = new PullSaga();
    const result = await saga.run({
      baseDir: directoryPath,
      remote,
      branch: branch || undefined,
      signal,
    });
    if (!result.success) {
      return { success: false, message: result.error };
    }

    const state = await this.getStateSnapshot(directoryPath);

    return {
      success: true,
      message: `${result.data.changes} files changed`,
      updatedFiles: result.data.changes,
      state,
    };
  }

  async publish(
    directoryPath: string,
    remote = "origin",
    signal?: AbortSignal,
    env?: Record<string, string>,
  ): Promise<PublishOutput> {
    const currentBranch = await getCurrentBranch(directoryPath);
    if (!currentBranch) {
      return { success: false, message: "No branch to publish", branch: "" };
    }

    const pushResult = await this.push(
      directoryPath,
      remote,
      currentBranch,
      true,
      signal,
      env,
    );
    return {
      success: pushResult.success,
      message: pushResult.message,
      branch: currentBranch,
      state: pushResult.state,
    };
  }

  async sync(
    directoryPath: string,
    remote = "origin",
    signal?: AbortSignal,
  ): Promise<SyncOutput> {
    const pullResult = await this.pull(
      directoryPath,
      remote,
      undefined,
      signal,
    );
    if (!pullResult.success) {
      return {
        success: false,
        pullMessage: pullResult.message,
        pushMessage: "Skipped due to pull failure",
      };
    }

    const pushResult = await this.push(
      directoryPath,
      remote,
      undefined,
      false,
      signal,
    );

    const state = await this.getStateSnapshot(directoryPath);

    return {
      success: pushResult.success,
      pullMessage: pullResult.message,
      pushMessage: pushResult.message,
      state,
    };
  }

  // --- git-pr group (pure gh-CLI PR/GitHub read ops) ---

  async getGhStatus(): Promise<GhStatusOutput> {
    const versionResult = await execGh(["--version"]);
    if (versionResult.exitCode !== 0) {
      return {
        installed: false,
        version: null,
        authenticated: false,
        username: null,
        error: versionResult.error ?? versionResult.stderr ?? null,
      };
    }

    const version = versionResult.stdout.split("\n")[0]?.trim() ?? null;
    const authResult = await execGh(["auth", "status"]);
    const authenticated = authResult.exitCode === 0;
    const authOutput = `${authResult.stdout}\n${authResult.stderr}`;
    const usernameMatch = authOutput.match(
      /Logged in to github.com (?:as |account )(\S+)/,
    );

    return {
      installed: true,
      version,
      authenticated,
      username: usernameMatch?.[1] ?? null,
      error: authenticated
        ? null
        : authResult.stderr || authResult.error || null,
    };
  }

  async getGhAuthToken(): Promise<GhAuthTokenOutput> {
    const result = await execGh(["auth", "token"]);
    if (result.exitCode !== 0) {
      return {
        success: false,
        token: null,
        error:
          result.stderr || result.error || "Failed to read GitHub auth token",
      };
    }

    const token = result.stdout.trim();
    if (!token) {
      return {
        success: false,
        token: null,
        error: "GitHub auth token is empty",
      };
    }

    return { success: true, token, error: null };
  }

  async getPrStatus(directoryPath: string): Promise<PrStatusOutput> {
    const base: PrStatusOutput = {
      hasRemote: false,
      isGitHubRepo: false,
      currentBranch: null,
      defaultBranch: null,
      prExists: false,
      prUrl: null,
      prState: null,
      baseBranch: null,
      headBranch: null,
      isDraft: null,
      error: null,
    };

    try {
      const remoteUrl = await getRemoteUrl(directoryPath);
      const isGitHubRepo = !!(remoteUrl && parseGithubUrl(remoteUrl));
      const currentBranch = await getCurrentBranch(directoryPath);
      const defaultBranch = await getDefaultBranch(directoryPath).catch(
        () => null,
      );

      if (!isGitHubRepo || !currentBranch) {
        return {
          ...base,
          hasRemote: !!remoteUrl,
          isGitHubRepo,
          currentBranch,
          defaultBranch,
        };
      }

      const prResult = await execGh(
        ["pr", "view", "--json", "url,state,baseRefName,headRefName,isDraft"],
        { cwd: directoryPath },
      );

      const shared = {
        hasRemote: true,
        isGitHubRepo: true,
        currentBranch,
        defaultBranch,
      };

      if (prResult.exitCode !== 0) {
        return { ...base, ...shared };
      }

      const data = JSON.parse(prResult.stdout) as {
        url?: string;
        state?: string;
        baseRefName?: string;
        headRefName?: string;
        isDraft?: boolean;
      };

      return {
        ...base,
        ...shared,
        prExists: !!data.url,
        prUrl: data.url ?? null,
        prState: data.state ?? null,
        baseBranch: data.baseRefName ?? null,
        headBranch: data.headRefName ?? null,
        isDraft: data.isDraft ?? null,
      };
    } catch (error) {
      return {
        ...base,
        error: error instanceof Error ? error.message : "Unknown error",
      };
    }
  }

  async getPrUrlForBranch(
    directoryPath: string,
    branchName: string,
  ): Promise<string | null> {
    try {
      const remoteUrl = await getRemoteUrl(directoryPath);
      if (!remoteUrl) return null;

      const parsed = parseGithubUrl(remoteUrl);
      if (!parsed) return null;

      const result = await execGh([
        "pr",
        "list",
        "--head",
        branchName,
        "--state",
        "all",
        "--json",
        "url",
        "--limit",
        "1",
        "--repo",
        `${parsed.owner}/${parsed.repo}`,
      ]);

      if (result.exitCode !== 0) {
        return null;
      }

      const data = JSON.parse(result.stdout) as Array<{ url?: string }>;
      return data[0]?.url ?? null;
    } catch {
      return null;
    }
  }

  async openPr(directoryPath: string): Promise<OpenPrOutput> {
    const result = await execGh(["pr", "view", "--json", "url"], {
      cwd: directoryPath,
    });

    if (result.exitCode !== 0) {
      return {
        success: false,
        message: result.stderr || result.error || "Failed to fetch PR",
        prUrl: null,
      };
    }

    const data = JSON.parse(result.stdout) as { url?: string };
    const prUrl = data.url ?? null;
    return { success: !!prUrl, message: prUrl ? "OK" : "No PR found", prUrl };
  }

  async getPrDetailsByUrl(prUrl: string): Promise<PrDetailsByUrlOutput | null> {
    const pr = parseGithubUrl(prUrl);
    if (pr?.kind !== "pr") return null;

    try {
      const result = await execGh([
        "api",
        `repos/${pr.owner}/${pr.repo}/pulls/${pr.number}`,
        "--jq",
        "{state,merged,draft,headRefName: .head.ref,title}",
      ]);

      if (result.exitCode !== 0) {
        return null;
      }

      const data = JSON.parse(result.stdout) as {
        state: string;
        merged: boolean;
        draft: boolean;
        headRefName: string | null;
        title: string | null;
      };

      return data;
    } catch {
      return null;
    }
  }

  async getPrInfoByUrl(prUrl: string): Promise<PrInfoByUrlOutput | null> {
    const pr = parseGithubUrl(prUrl);
    if (pr?.kind !== "pr") return null;

    try {
      const result = await execGh([
        "api",
        `repos/${pr.owner}/${pr.repo}/pulls/${pr.number}`,
        "--jq",
        '{number,title,body: (.body // ""),author: .user.login,state,merged,draft,mergeable,mergeStateStatus: (.mergeable_state // "unknown"),baseRefName: .base.ref,headRefName: .head.ref,additions,deletions,changedFiles: .changed_files}',
      ]);

      if (result.exitCode !== 0) {
        return null;
      }

      // Zod-parse rather than cast, so a GitHub response-shape change
      // surfaces here (caught, -> null) instead of leaking bad data.
      return getPrInfoByUrlOutput.parse(JSON.parse(result.stdout));
    } catch {
      return null;
    }
  }

  async getPrChangedFiles(prUrl: string): Promise<ChangedFile[]> {
    const pr = parseGithubUrl(prUrl);
    if (pr?.kind !== "pr") return [];

    const { owner, repo, number } = pr;

    const result = await execGh([
      "api",
      `repos/${owner}/${repo}/pulls/${number}/files`,
      "--paginate",
      "--slurp",
    ]);

    if (result.exitCode !== 0) {
      throw new Error(
        `Failed to fetch PR files: ${result.stderr || result.error || "Unknown error"}`,
      );
    }

    const pages = JSON.parse(result.stdout) as Array<
      Array<{
        filename: string;
        status: string;
        previous_filename?: string;
        additions: number;
        deletions: number;
        patch?: string;
        sha?: string;
      }>
    >;
    const files = pages.flat();

    return files.map((f) => {
      let status: ChangedFile["status"];
      switch (f.status) {
        case "added":
          status = "added";
          break;
        case "removed":
          status = "deleted";
          break;
        case "renamed":
          status = "renamed";
          break;
        default:
          status = "modified";
          break;
      }

      return {
        path: f.filename,
        status,
        originalPath: f.previous_filename,
        linesAdded: f.additions,
        linesRemoved: f.deletions,
        sha: f.sha,
        patch: f.patch
          ? toUnifiedDiffPatch(f.patch, f.filename, f.previous_filename, status)
          : undefined,
      };
    });
  }

  /**
   * Batch-fetch coarse diff stats (additions / deletions / changedFiles) for
   * many GitHub PR URLs via GitHub GraphQL alias-batching.
   */
  async getPrDiffStatsBatch(
    prUrls: string[],
  ): Promise<Record<string, PrDiffStats>> {
    if (prUrls.length === 0) return {};

    interface ParsedPr {
      owner: string;
      repo: string;
      number: number;
    }

    const grouped = new Map<string, { parsed: ParsedPr; urls: string[] }>();
    for (const url of prUrls) {
      const pr = parseGithubUrl(url);
      if (pr?.kind !== "pr") continue;
      const key = `${pr.owner.toLowerCase()}/${pr.repo.toLowerCase()}#${pr.number}`;
      const existing = grouped.get(key);
      if (existing) {
        existing.urls.push(url);
      } else {
        grouped.set(key, {
          parsed: { owner: pr.owner, repo: pr.repo, number: pr.number },
          urls: [url],
        });
      }
    }

    if (grouped.size === 0) return {};

    const entries = Array.from(grouped.entries());
    const chunks: Array<typeof entries> = [];
    for (let i = 0; i < entries.length; i += PR_DIFF_STATS_BATCH_CHUNK_SIZE) {
      chunks.push(entries.slice(i, i + PR_DIFF_STATS_BATCH_CHUNK_SIZE));
    }

    const out: Record<string, PrDiffStats> = {};
    const chunkResults = await Promise.all(
      chunks.map((chunk) => this.fetchPrDiffStatsChunk(chunk)),
    );
    for (const chunkOut of chunkResults) {
      Object.assign(out, chunkOut);
    }
    return out;
  }

  private async fetchPrDiffStatsChunk(
    chunk: Array<
      [
        string,
        {
          parsed: { owner: string; repo: string; number: number };
          urls: string[];
        },
      ]
    >,
  ): Promise<Record<string, PrDiffStats>> {
    const aliasFragments = chunk
      .map(([, { parsed }], index) => {
        return `pr${index}: repository(owner: "${escapeGraphqlString(parsed.owner)}", name: "${escapeGraphqlString(parsed.repo)}") { pullRequest(number: ${parsed.number}) { additions deletions changedFiles state isDraft } }`;
      })
      .join("\n");
    const query = `query InboxPrDiffStatsBatch {\n${aliasFragments}\n}`;

    const result = await execGh(["api", "graphql", "-f", `query=${query}`]);

    if (result.exitCode !== 0) {
      throw new Error(
        `Failed to fetch PR diff stats batch: ${result.stderr || result.error || "Unknown error"}`,
      );
    }

    const parsed = JSON.parse(result.stdout) as {
      data?: Record<
        string,
        {
          pullRequest?: {
            additions: number;
            deletions: number;
            changedFiles: number;
            state: string;
            isDraft: boolean;
          } | null;
        } | null
      >;
    };

    const out: Record<string, PrDiffStats> = {};
    for (let i = 0; i < chunk.length; i += 1) {
      const [, { urls }] = chunk[i];
      const node = parsed.data?.[`pr${i}`]?.pullRequest;
      if (!node) continue;
      // GraphQL `PullRequestState` is OPEN | CLOSED | MERGED; normalise to the
      // lowercase state + merged boolean shape the badge expects.
      const stats: PrDiffStats = {
        additions: node.additions,
        deletions: node.deletions,
        changedFiles: node.changedFiles,
        state: normalizeGraphqlPrState(node.state),
        merged: node.state === "MERGED",
        draft: node.isDraft,
      };
      for (const url of urls) {
        out[url] = stats;
      }
    }
    return out;
  }

  async getBranchChangedFiles(
    repo: string,
    branch: string,
  ): Promise<ChangedFile[]> {
    const parts = repo.split("/");
    if (parts.length !== 2) return [];

    const [owner, repoName] = parts;

    const repoResult = await execGh([
      "api",
      `repos/${owner}/${repoName}`,
      "--jq",
      ".default_branch",
    ]);

    if (repoResult.exitCode !== 0 || !repoResult.stdout.trim()) {
      return [];
    }
    const defaultBranch = repoResult.stdout.trim();

    const result = await execGh([
      "api",
      `repos/${owner}/${repoName}/compare/${defaultBranch}...${branch}`,
    ]);

    if (result.exitCode !== 0) {
      throw new Error(
        `Failed to fetch branch files: ${result.stderr || result.error || "Unknown error"}`,
      );
    }

    const response = JSON.parse(result.stdout) as {
      files?: Array<{
        filename: string;
        status: string;
        previous_filename?: string;
        additions: number;
        deletions: number;
        patch?: string;
        sha?: string;
      }>;
    };
    const files = response.files;

    if (!files) return [];

    return files.map((f) => {
      let status: ChangedFile["status"];
      switch (f.status) {
        case "added":
          status = "added";
          break;
        case "removed":
          status = "deleted";
          break;
        case "renamed":
          status = "renamed";
          break;
        default:
          status = "modified";
          break;
      }

      return {
        path: f.filename,
        status,
        originalPath: f.previous_filename,
        linesAdded: f.additions,
        linesRemoved: f.deletions,
        sha: f.sha,
        patch: f.patch
          ? toUnifiedDiffPatch(f.patch, f.filename, f.previous_filename, status)
          : undefined,
      };
    });
  }

  async getLocalBranchChangedFiles(
    directoryPath: string,
    branch: string,
  ): Promise<ChangedFile[]> {
    await this.fetchIfStale(directoryPath);

    const defaultBranch = await getDefaultBranch(directoryPath);
    if (!defaultBranch) return [];

    const files = await getChangedFilesBetweenBranches(
      directoryPath,
      defaultBranch,
      branch,
      { excludePatterns: [".claude", "CLAUDE.local.md"] },
    );
    if (files.length === 0) return [];

    const patchByPath = await getBranchDiffPatchesByPath(
      directoryPath,
      defaultBranch,
      branch,
    );

    return files.map((f) => ({
      path: f.path,
      status: f.status,
      originalPath: f.originalPath,
      linesAdded: f.linesAdded,
      linesRemoved: f.linesRemoved,
      patch: patchByPath.get(f.path),
    }));
  }

  async updatePrByUrl(
    prUrl: string,
    action: PrActionType,
  ): Promise<UpdatePrByUrlOutput> {
    const pr = parseGithubUrl(prUrl);
    if (pr?.kind !== "pr") {
      return { success: false, message: "Invalid PR URL" };
    }

    try {
      const args =
        action === "draft"
          ? ["pr", "ready", "--undo", String(pr.number)]
          : ["pr", action, String(pr.number)];

      const result = await execGh([
        ...args,
        "--repo",
        `${pr.owner}/${pr.repo}`,
      ]);

      if (result.exitCode !== 0) {
        return {
          success: false,
          message: result.stderr || result.error || "Unknown error",
        };
      }

      return { success: true, message: result.stdout };
    } catch (error) {
      return {
        success: false,
        message: error instanceof Error ? error.message : "Unknown error",
      };
    }
  }

  async approvePr(prUrl: string): Promise<ApprovePrOutput> {
    const pr = parseGithubUrl(prUrl);
    if (pr?.kind !== "pr") {
      return { success: false, message: "Invalid PR URL" };
    }

    try {
      const result = await execGh([
        "pr",
        "review",
        String(pr.number),
        "--approve",
        "--repo",
        `${pr.owner}/${pr.repo}`,
      ]);

      if (result.exitCode !== 0) {
        return {
          success: false,
          message: result.stderr || result.error || "Unknown error",
        };
      }

      return { success: true, message: result.stdout };
    } catch (error) {
      return {
        success: false,
        message: error instanceof Error ? error.message : "Unknown error",
      };
    }
  }

  async mergePr(prUrl: string, method: PrMergeMethod): Promise<MergePrOutput> {
    const pr = parseGithubUrl(prUrl);
    if (pr?.kind !== "pr") {
      return { success: false, message: "Invalid PR URL" };
    }

    try {
      const result = await execGh([
        "pr",
        "merge",
        String(pr.number),
        `--${method}`,
        "--repo",
        `${pr.owner}/${pr.repo}`,
      ]);

      if (result.exitCode !== 0) {
        return {
          success: false,
          message: result.stderr || result.error || "Unknown error",
        };
      }

      return { success: true, message: result.stdout };
    } catch (error) {
      return {
        success: false,
        message: error instanceof Error ? error.message : "Unknown error",
      };
    }
  }

  async getPrChecks(prUrl: string): Promise<GetPrChecksOutput> {
    const pr = parseGithubUrl(prUrl);
    if (pr?.kind !== "pr") return null;

    try {
      // `gh pr checks` exits non-zero when checks are failing (1) or pending
      // (8), so the exit code alone doesn't distinguish "couldn't fetch" from
      // "fetched, some red" — parse stdout instead.
      const result = await execGh([
        "pr",
        "checks",
        String(pr.number),
        "--repo",
        `${pr.owner}/${pr.repo}`,
        "--json",
        "name,bucket,link,workflow,description",
      ]);

      if (result.stdout.trim()) {
        const checks = JSON.parse(result.stdout) as Array<{
          name?: string;
          bucket?: string;
          link?: string;
          workflow?: string;
          description?: string;
        }>;
        return checks.map(
          (check): PrCheck => ({
            name: check.name ?? "",
            bucket: normalizeCheckBucket(check.bucket),
            link: check.link || null,
            workflow: check.workflow || null,
            description: check.description || null,
          }),
        );
      }

      if (result.exitCode === 0) return [];
      // A PR with no CI configured is not an error state.
      if ((result.stderr ?? "").includes("no checks reported")) return [];
      return null;
    } catch {
      return null;
    }
  }

  async getPrComments(prUrl: string): Promise<GetPrCommentsOutput> {
    const pr = parseGithubUrl(prUrl);
    if (pr?.kind !== "pr") return null;

    // GitHub's conversation tab is two feeds: issue comments and review
    // summaries ("approved with a comment"). Inline code comments come from
    // getPrReviewComments separately.
    const [comments, reviewSummaries] = await Promise.all([
      this.fetchPrCommentFeed(
        `repos/${pr.owner}/${pr.repo}/issues/${pr.number}/comments`,
        '.[] | {id, author: (.user.login // "unknown"), avatarUrl: (.user.avatar_url // null), body: (.body // ""), createdAt: .created_at, url: (.html_url // null)}',
      ),
      this.fetchPrCommentFeed(
        `repos/${pr.owner}/${pr.repo}/pulls/${pr.number}/reviews`,
        '.[] | select(.state != "PENDING") | select((.body // "") != "") | {id, author: (.user.login // "unknown"), avatarUrl: (.user.avatar_url // null), body, createdAt: (.submitted_at // ""), url: (.html_url // null)}',
      ),
    ]);
    return [...comments, ...reviewSummaries];
  }

  /**
   * Fetch a paginated comment-shaped feed, slimmed to the schema fields in
   * gh's jq (full comment objects are mostly boilerplate URLs and can blow
   * past the exec buffer on busy PRs). `--jq` with `--paginate` emits one
   * compact JSON object per line. Throws on failure so the renderer can show
   * why (rate limit, auth, network) instead of a silent empty section.
   */
  private async fetchPrCommentFeed(
    endpoint: string,
    jq: string,
  ): Promise<PrConversationComment[]> {
    const result = await execGh(["api", endpoint, "--paginate", "--jq", jq]);

    if (result.exitCode !== 0) {
      throw new Error(
        `Failed to fetch PR comments: ${result.stderr || result.error || "Unknown error"}`,
      );
    }

    return result.stdout
      .split("\n")
      .filter((line) => line.trim() !== "")
      .map((line) => prConversationCommentSchema.parse(JSON.parse(line)));
  }

  async getPrReviewComments(prUrl: string): Promise<PrReviewThread[]> {
    const pr = parseGithubUrl(prUrl);
    if (pr?.kind !== "pr") return [];

    const { owner, repo, number } = pr;

    // Position fields (line, side, etc.) live on the thread, not on individual comments.
    const query = `
      query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
        repository(owner: $owner, name: $repo) {
          pullRequest(number: $number) {
            reviewThreads(first: 100, after: $cursor) {
              pageInfo { hasNextPage endCursor }
              nodes {
                id
                isResolved
                isOutdated
                path
                diffSide
                line
                originalLine
                startLine
                startDiffSide
                subjectType
                comments(first: 100) {
                  nodes {
                    databaseId
                    body
                    path
                    diffHunk
                    replyTo { databaseId }
                    author { login avatarUrl }
                    createdAt
                    updatedAt
                  }
                }
              }
            }
          }
        }
      }
    `;

    type ThreadNode = {
      id: string;
      isResolved: boolean;
      isOutdated: boolean;
      path: string;
      diffSide: "LEFT" | "RIGHT";
      line: number | null;
      originalLine: number | null;
      startLine: number | null;
      startDiffSide: "LEFT" | "RIGHT" | null;
      subjectType: "LINE" | "FILE" | null;
      comments: {
        nodes: Array<{
          databaseId: number;
          body: string;
          path: string;
          diffHunk: string;
          replyTo: { databaseId: number } | null;
          author: { login: string; avatarUrl: string };
          createdAt: string;
          updatedAt: string;
        }>;
      };
    };

    type PageResponse = {
      data: {
        repository: {
          pullRequest: {
            reviewThreads: {
              pageInfo: { hasNextPage: boolean; endCursor: string | null };
              nodes: ThreadNode[];
            };
          };
        };
      };
      errors?: Array<{ message: string }>;
    };

    const MAX_THREAD_PAGES = 50; // 50 × 100 = 5 000 threads max

    const allNodes: ThreadNode[] = [];
    let cursor: string | null = null;

    for (let page = 0; page < MAX_THREAD_PAGES; page++) {
      const result = await execGh(["api", "graphql", "--input", "-"], {
        input: JSON.stringify({
          query,
          variables: { owner, repo, number, cursor },
        }),
      });

      if (result.exitCode !== 0) {
        throw new Error(
          `Failed to fetch PR review threads: ${result.stderr || result.error || "Unknown error"}`,
        );
      }

      const data = JSON.parse(result.stdout) as PageResponse;
      if (data.errors?.length) {
        throw new Error(
          `GraphQL error: ${data.errors.map((e) => e.message).join("; ")}`,
        );
      }
      const reviewThreads = data.data.repository.pullRequest.reviewThreads;
      allNodes.push(...reviewThreads.nodes);
      if (!reviewThreads.pageInfo.hasNextPage) {
        break;
      }
      cursor = reviewThreads.pageInfo.endCursor;
    }

    return allNodes.map((thread) => {
      const comments: PrReviewComment[] = thread.comments.nodes.map((c) => ({
        id: c.databaseId,
        body: c.body,
        path: c.path,
        diff_hunk: c.diffHunk,
        line: thread.line,
        original_line: thread.originalLine,
        side: thread.diffSide,
        start_line: thread.startLine,
        start_side: thread.startDiffSide,
        in_reply_to_id: c.replyTo?.databaseId ?? null,
        user: { login: c.author.login, avatar_url: c.author.avatarUrl },
        created_at: c.createdAt,
        updated_at: c.updatedAt,
        subject_type: thread.subjectType
          ? (thread.subjectType.toLowerCase() as "line" | "file")
          : null,
      }));

      return {
        nodeId: thread.id,
        isResolved: thread.isResolved,
        rootId: comments[0]?.id ?? 0,
        filePath: thread.path,
        comments,
      };
    });
  }

  async resolveReviewThread(
    threadNodeId: string,
    resolved: boolean,
  ): Promise<ResolveReviewThreadOutput> {
    const mutation = resolved
      ? `mutation($threadId: ID!) { resolveReviewThread(input: { threadId: $threadId }) { thread { id isResolved } } }`
      : `mutation($threadId: ID!) { unresolveReviewThread(input: { threadId: $threadId }) { thread { id isResolved } } }`;

    try {
      const result = await execGh(["api", "graphql", "--input", "-"], {
        input: JSON.stringify({
          query: mutation,
          variables: { threadId: threadNodeId },
        }),
      });

      if (result.exitCode !== 0) {
        return { success: false, isResolved: !resolved };
      }

      const data = JSON.parse(result.stdout) as {
        data: {
          resolveReviewThread?: { thread: { isResolved: boolean } };
          unresolveReviewThread?: { thread: { isResolved: boolean } };
        };
        errors?: Array<{ message: string }>;
      };
      if (data.errors?.length) {
        return { success: false, isResolved: !resolved };
      }
      const thread =
        data.data.resolveReviewThread?.thread ??
        data.data.unresolveReviewThread?.thread;

      return { success: true, isResolved: thread?.isResolved ?? resolved };
    } catch {
      return { success: false, isResolved: !resolved };
    }
  }

  async replyToPrComment(
    prUrl: string,
    commentId: number,
    body: string,
  ): Promise<ReplyToPrCommentOutput> {
    const pr = parseGithubUrl(prUrl);
    if (pr?.kind !== "pr") {
      return { success: false, comment: null };
    }

    try {
      const result = await execGh([
        "api",
        `repos/${pr.owner}/${pr.repo}/pulls/${pr.number}/comments/${commentId}/replies`,
        "-X",
        "POST",
        "-f",
        `body=${body}`,
      ]);

      if (result.exitCode !== 0) {
        return { success: false, comment: null };
      }

      const data = JSON.parse(result.stdout) as PrReviewComment;
      return { success: true, comment: data };
    } catch {
      return { success: false, comment: null };
    }
  }

  async getPrTemplate(directoryPath: string): Promise<GetPrTemplateOutput> {
    const templatePaths = [
      ".github/PULL_REQUEST_TEMPLATE.md",
      ".github/pull_request_template.md",
      "PULL_REQUEST_TEMPLATE.md",
      "pull_request_template.md",
      "docs/PULL_REQUEST_TEMPLATE.md",
    ];

    for (const relativePath of templatePaths) {
      const fullPath = path.join(directoryPath, relativePath);
      try {
        const content = await fs.promises.readFile(fullPath, "utf-8");
        return { template: content, templatePath: relativePath };
      } catch {}
    }

    return { template: null, templatePath: null };
  }

  async getCommitConventions(
    directoryPath: string,
    sampleSize = 20,
  ): Promise<GetCommitConventionsOutput> {
    return getCommitConventions(directoryPath, sampleSize);
  }

  private async resolveCanonicalRepo(repo: string): Promise<string> {
    const result = await execGh([
      "repo",
      "view",
      repo,
      "--json",
      "name,owner",
      "--jq",
      '.owner.login + "/" + .name',
    ]);
    if (result.exitCode !== 0) return repo;
    return result.stdout.trim() || repo;
  }

  private normalizeRefState(raw: string): GithubRef["state"] {
    const upper = raw.toUpperCase();
    if (upper === "OPEN") return "OPEN";
    if (upper === "MERGED") return "MERGED";
    return "CLOSED";
  }

  private parseGhRefs(
    stdout: string,
    repo: string,
    kind: GithubRefKind,
  ): GithubRef[] {
    const raw = JSON.parse(stdout) as Array<{
      number: number;
      title: string;
      state: string;
      labels?: Array<{ name: string }>;
      url: string;
      isDraft?: boolean;
    }>;
    const items = Array.isArray(raw) ? raw : [raw];
    return items.map((item) => {
      // GitHub's issues API returns PRs too, so derive kind from the URL path.
      const resolvedKind: GithubRefKind = item.url.includes("/pull/")
        ? "pr"
        : kind;
      return {
        kind: resolvedKind,
        number: item.number,
        title: item.title,
        state: this.normalizeRefState(item.state),
        labels: (item.labels ?? []).map((l) => l.name),
        url: item.url,
        repo,
        isDraft: resolvedKind === "pr" ? Boolean(item.isDraft) : undefined,
      };
    });
  }

  async searchGithubRefs(
    directoryPath: string,
    query?: string,
    limit = 5,
    kinds: GithubRefKind[] = ["issue", "pr"],
  ): Promise<GithubRef[]> {
    const repoInfo = await this.getGitRepoInfo(directoryPath);
    if (!repoInfo) return [];

    // Full GitHub URL: look up directly. May target a different repo than the local one.
    const urlRef = parseGithubUrl(query);
    if (urlRef && urlRef.kind !== "repo" && kinds.includes(urlRef.kind)) {
      const repoSlug = `${urlRef.owner}/${urlRef.repo}`;
      return this.fetchGhRefs(
        [urlRef.kind, "view", String(urlRef.number), "--repo", repoSlug],
        repoSlug,
        urlRef.kind,
      );
    }

    const repo = await this.resolveCanonicalRepo(
      `${repoInfo.organization}/${repoInfo.repository}`,
    );

    const trimmed = query?.trim().replace(/^#/, "");
    const refNumber = trimmed ? Number(trimmed) : Number.NaN;

    // Number lookup: `gh issue view` returns PRs too (shared number space).
    if (!Number.isNaN(refNumber) && Number.isInteger(refNumber)) {
      return this.fetchGhRefs(
        ["issue", "view", String(refNumber), "--repo", repo],
        repo,
        "issue",
      );
    }

    // Text search: one call via `gh search issues --include-prs` when both kinds are wanted.
    if (trimmed) {
      const includeIssues = kinds.includes("issue");
      const includePrs = kinds.includes("pr");
      const searchNoun = !includeIssues && includePrs ? "prs" : "issues";
      const args = [
        "search",
        searchNoun,
        trimmed,
        "--repo",
        repo,
        "--limit",
        String(limit),
        "--match",
        "title",
      ];
      if (searchNoun === "issues" && includePrs) args.push("--include-prs");
      return this.fetchGhRefs(args, repo, "issue");
    }

    // Empty query: list defaults per-kind in parallel (`gh search` requires a query).
    const tasks: Promise<GithubRef[]>[] = [];
    if (kinds.includes("issue")) {
      tasks.push(
        this.fetchGhRefs(
          [
            "issue",
            "list",
            "--repo",
            repo,
            "--limit",
            String(limit),
            "--state",
            "all",
          ],
          repo,
          "issue",
        ),
      );
    }
    if (kinds.includes("pr")) {
      tasks.push(
        this.fetchGhRefs(
          [
            "pr",
            "list",
            "--repo",
            repo,
            "--limit",
            String(limit),
            "--state",
            "all",
          ],
          repo,
          "pr",
        ),
      );
    }
    const results = await Promise.all(tasks);
    return this.sortRefs(this.dedupeRefsByUrl(results.flat()));
  }

  private dedupeRefsByUrl(refs: GithubRef[]): GithubRef[] {
    const byUrl = new Map<string, GithubRef>();
    for (const ref of refs) {
      if (!byUrl.has(ref.url)) byUrl.set(ref.url, ref);
    }
    return [...byUrl.values()];
  }

  private sortRefs(refs: GithubRef[]): GithubRef[] {
    return refs.sort((a, b) => b.number - a.number);
  }

  async getGithubIssue(
    owner: string,
    repo: string,
    number: number,
  ): Promise<GithubRef | null> {
    const repoSlug = `${owner}/${repo}`;
    const refs = await this.fetchGhRefs(
      ["issue", "view", String(number), "--repo", repoSlug],
      repoSlug,
      "issue",
    );
    return refs[0] ?? null;
  }

  async getGithubPullRequest(
    owner: string,
    repo: string,
    number: number,
  ): Promise<GithubRef | null> {
    const repoSlug = `${owner}/${repo}`;
    const refs = await this.fetchGhRefs(
      ["pr", "view", String(number), "--repo", repoSlug],
      repoSlug,
      "pr",
    );
    return refs[0] ?? null;
  }

  private async fetchGhRefs(
    args: string[],
    repo: string,
    kind: GithubRefKind,
  ): Promise<GithubRef[]> {
    const jsonFields =
      kind === "pr"
        ? "number,title,state,url,isDraft"
        : "number,title,state,labels,url";
    const result = await execGh([...args, "--json", jsonFields]);
    if (result.exitCode !== 0) return [];

    try {
      return this.parseGhRefs(result.stdout, repo, kind);
    } catch {
      return [];
    }
  }

  async readHandoffLocalGitState(
    directoryPath: string,
  ): Promise<HandoffLocalGitState> {
    return readHandoffLocalGitState(directoryPath);
  }

  async cleanupAfterCloudHandoff(
    directoryPath: string,
    branchName: string | null,
  ): Promise<{
    stashed: boolean;
    switched: boolean;
    defaultBranch: string | null;
  }> {
    let stashed = false;
    const hasChanges =
      (await this.getChangedFilesHead(directoryPath)).length > 0;

    if (hasChanges) {
      const label = branchName ?? "unknown";
      const stashResult = await new StashPushSaga().run({
        baseDir: directoryPath,
        message: `posthog-code: handoff backup (${label})`,
      });
      if (!stashResult.success) {
        return { stashed: false, switched: false, defaultBranch: null };
      }
      stashed = true;
    }

    const resetResult = await new ResetToDefaultBranchSaga().run({
      baseDir: directoryPath,
    });
    if (!resetResult.success) {
      return { stashed, switched: false, defaultBranch: null };
    }

    return {
      stashed,
      switched: resetResult.data.switched,
      defaultBranch: resetResult.data.defaultBranch,
    };
  }
}
