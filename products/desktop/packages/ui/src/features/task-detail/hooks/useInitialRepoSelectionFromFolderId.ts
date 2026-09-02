import { parseRepository, type WorkspaceMode } from "@posthog/shared";
import { useEffect, useRef } from "react";
import type { RegisteredFolder } from "../../folders/types";
import type { LocalWorkspaceMode } from "../../settings/settingsStore";

export interface ReposReadyInput {
  /** True while the integrations + per-installation repo queries are in flight. */
  isLoadingRepos: boolean;
  /** Number of connectable `owner/repo` slugs currently known. */
  repositoriesCount: number;
  /** Whether the user has any connected GitHub integration at all. */
  hasGithubIntegration: boolean;
}

/**
 * Whether the cloud-repo list has *settled*, i.e. it's safe to conclude a folder is or
 * isn't cloud-capable. Distinguishes "settled empty because the user has no GitHub
 * integration" (ready) from "transiently empty while per-installation repo queries are
 * still producing data" (not ready). The latter window is real: `isLoadingRepos` can flip
 * false before `repositories` populates (see the validation effect in TaskInput), so
 * `!isLoadingRepos` alone would mis-judge a cloud-capable repo during that gap.
 */
export function areReposReady({
  isLoadingRepos,
  repositoriesCount,
  hasGithubIntegration,
}: ReposReadyInput): boolean {
  if (isLoadingRepos) return false;
  return repositoriesCount > 0 || !hasGithubIntegration;
}

export interface RepoSelectionInput {
  /** The group's registered local folder, absent for cloud-only repos. */
  folder?: RegisteredFolder;
  /**
   * `owner/repo` the sidebar group stands for. Carries the repo for groups with
   * no registered folder — cloud-only ones — which otherwise had nothing to
   * prefill from and left the previous pick in place.
   */
  folderRepository?: string;
  /** Lower-cased `owner/repo` slugs the user can use in cloud mode. */
  repositories: string[];
  /** Whether the integrations list has finished loading (gate the mode switch). */
  reposLoaded: boolean;
  currentMode: WorkspaceMode;
  /** Mode to fall back to when leaving cloud (local or worktree). */
  lastUsedLocalMode: LocalWorkspaceMode;
  /**
   * Environment ("local" | "cloud") of this repo's most recent visible run, used
   * to prefill the mode. `undefined` when nothing visible has run yet — then we
   * fall back to the user's current (global last-used) mode.
   */
  mostRecentEnvironment?: "local" | "cloud";
}

export interface RepoSelection {
  /** Local directory to select, or undefined when the group has no folder. */
  directory?: string;
  /** Cloud `owner/repo` slug to select, or undefined to leave the cloud pick as-is. */
  cloudRepository?: string;
  /**
   * Workspace mode to switch to, or undefined to keep the current mode. Can be
   * `"cloud"` when the repo's most recent run was in the cloud, so this is the full
   * `WorkspaceMode` rather than the local-only fallback type.
   */
  nextMode?: WorkspaceMode;
}

/**
 * Pure resolver: given the group a user picked (e.g. via the sidebar "+"), decide
 * what to select in both the local-directory and cloud-repo pickers, and whether the
 * workspace mode must change.
 *
 * Rules: always prefill the local directory and (when cloud-capable) the cloud repo.
 * The mode follows the repo's own most recent visible run — open Local for a repo last
 * run locally, Cloud for one last run in the cloud — falling back to the user's current
 * (global last-used) mode only when nothing visible has run yet. A desired Cloud mode is
 * honoured only when the repo has a connected cloud counterpart; otherwise it drops to
 * the last-used local mode. A desired Local mode keeps the current mode when it's already
 * local (preserving worktree), and otherwise switches to the last-used local mode.
 *
 * A group with no registered folder is only workable in the cloud, so it has no
 * directory to prefill and its mode follows cloud-capability alone.
 */
export function resolveRepoSelectionForFolder({
  folder,
  folderRepository,
  repositories,
  reposLoaded,
  currentMode,
  lastUsedLocalMode,
  mostRecentEnvironment,
}: RepoSelectionInput): RepoSelection {
  const slug = (folder?.remoteUrl ?? folderRepository)?.toLowerCase();
  // A group is cloud-capable only when its remote is a real `owner/repo` (guards against
  // legacy single-segment values and folder-path group ids) AND that repo is one of the
  // user's connected integrations.
  const cloudRepository =
    slug && parseRepository(slug) !== null && repositories.includes(slug)
      ? slug
      : undefined;

  const selection: RepoSelection = {
    directory: folder?.path,
    cloudRepository,
  };

  // Only decide the mode once the integrations list has loaded, so cloud-capability is
  // known and we never switch out of cloud while the repo list is still in flight.
  if (reposLoaded) {
    const targetMode = resolveTargetMode({
      hasFolder: folder !== undefined,
      cloudRepository,
      currentMode,
      lastUsedLocalMode,
      mostRecentEnvironment,
    });
    if (targetMode !== currentMode) {
      selection.nextMode = targetMode;
    }
  }

  return selection;
}

function resolveTargetMode({
  hasFolder,
  cloudRepository,
  currentMode,
  lastUsedLocalMode,
  mostRecentEnvironment,
}: {
  hasFolder: boolean;
  cloudRepository: string | undefined;
  currentMode: WorkspaceMode;
  lastUsedLocalMode: LocalWorkspaceMode;
  mostRecentEnvironment?: "local" | "cloud";
}): WorkspaceMode {
  // Nothing is checked out locally, so a local mode would leave the previous repo's
  // directory selected — go to cloud when we can, otherwise leave the mode alone.
  if (!hasFolder) return cloudRepository ? "cloud" : currentMode;
  // Prefer the repo's own most recent run; fall back to the current global mode.
  const desiredEnvironment =
    mostRecentEnvironment ?? (currentMode === "cloud" ? "cloud" : "local");
  if (desiredEnvironment === "cloud" && cloudRepository) return "cloud";
  return currentMode === "cloud" ? lastUsedLocalMode : currentMode;
}

export interface UseInitialRepoSelectionParams {
  folderId: string | undefined;
  /**
   * `owner/repo` the picked sidebar group stands for, used when the group has no
   * registered folder (see {@link RepoSelectionInput.folderRepository}).
   */
  folderRepository?: string;
  /**
   * Identifier of the navigation request that carried the folder prefill. Each
   * "+" click issues a fresh id, so re-picking the same folder re-applies the
   * prefill even when the screen stayed mounted (the once-per-request guards
   * key on it). Without it, guards key on `folderId` alone.
   */
  requestId?: string;
  folders: RegisteredFolder[];
  /** Whether the folders list has finished loading. */
  foldersLoaded: boolean;
  /** Lower-cased `owner/repo` slugs the user can use in cloud mode. */
  repositories: string[];
  /** Whether the integrations list has finished loading (gate the mode switch). */
  reposLoaded: boolean;
  currentMode: WorkspaceMode;
  /** Mode to fall back to when leaving cloud (local or worktree). */
  lastUsedLocalMode: LocalWorkspaceMode;
  /**
   * Environment of this repo's most recent visible run, used to prefill the mode.
   * `undefined` falls back to the current global mode.
   */
  mostRecentEnvironment?: "local" | "cloud";
  setSelectedDirectory: (path: string) => void;
  setSelectedRepository: (repo: string) => void;
  /** Switches the workspace mode (without persisting it as the user's preference). */
  switchWorkspaceMode: (mode: WorkspaceMode) => void;
}

/**
 * Applies {@link resolveRepoSelectionForFolder} to the live pickers when a group prefill
 * arrives, syncing both the local directory and the cloud repo and switching mode when
 * required. Runs once per prefill (guarded by refs) so it never clobbers a repo/mode the
 * user changed afterward, and re-runs when the picked group changes.
 *
 * The dependency on `folders` / `repositories` lets the sync still fire when those lists
 * load after the initial mount.
 */
export function useInitialRepoSelectionFromFolderId({
  folderId,
  folderRepository,
  requestId,
  folders,
  foldersLoaded,
  repositories,
  reposLoaded,
  currentMode,
  lastUsedLocalMode,
  mostRecentEnvironment,
  setSelectedDirectory,
  setSelectedRepository,
  switchWorkspaceMode,
}: UseInitialRepoSelectionParams) {
  // Two guards: the local directory syncs immediately (once the folder loads), while the
  // cloud repo + mode decision waits for the integrations list, so it isn't marked "done"
  // before it can tell whether the repo is cloud-capable.
  const dirInitRef = useRef<string | undefined>(undefined);
  const repoModeInitRef = useRef<string | undefined>(undefined);
  // Read the current mode through a ref so it doesn't retrigger the effect (which would
  // re-run the once-per-folderId logic after we change the mode ourselves).
  const currentModeRef = useRef(currentMode);
  currentModeRef.current = currentMode;

  useEffect(() => {
    if (!folderId && !folderRepository) {
      dirInitRef.current = undefined;
      repoModeInitRef.current = undefined;
      return;
    }
    // A fresh requestId makes this a new prefill request even for the same
    // group, so clicking a group's "+" always re-selects its repo.
    const requestKey = `${requestId ?? ""}:${folderId ?? folderRepository}`;
    const folder = folderId
      ? folders.find((f) => f.id === folderId)
      : undefined;
    // Wait for a folder that is expected but hasn't loaded yet. Only while the
    // list is loading, though: a folderId left over from a removed folder never
    // resolves, and blocking on it would strand the repo prefill for good.
    if (folderId && !folder && !foldersLoaded) return;

    const selection = resolveRepoSelectionForFolder({
      folder,
      folderRepository,
      repositories,
      reposLoaded,
      currentMode: currentModeRef.current,
      lastUsedLocalMode,
      mostRecentEnvironment,
    });

    if (selection.directory && dirInitRef.current !== requestKey) {
      setSelectedDirectory(selection.directory);
      dirInitRef.current = requestKey;
    }

    // Defer the cloud/mode decision until the integrations list has loaded.
    if (reposLoaded && repoModeInitRef.current !== requestKey) {
      if (selection.cloudRepository) {
        setSelectedRepository(selection.cloudRepository);
      }
      if (selection.nextMode && selection.nextMode !== currentModeRef.current) {
        switchWorkspaceMode(selection.nextMode);
      }
      repoModeInitRef.current = requestKey;
    }
  }, [
    folderId,
    folderRepository,
    requestId,
    folders,
    foldersLoaded,
    repositories,
    reposLoaded,
    lastUsedLocalMode,
    mostRecentEnvironment,
    setSelectedDirectory,
    setSelectedRepository,
    switchWorkspaceMode,
  ]);
}
