import path from "node:path";

/**
 * Folder holding per-task scratch working directories for repo-less channel
 * tasks (the "generic chat box"). A repo-less channel session runs here instead
 * of in a git workspace; the agent clones a repo into a subdirectory only if it
 * decides it needs one.
 *
 * The name is shared so both the WorkspaceService (which creates scratch dirs)
 * and the AgentService (which detects them to enable channel-mode behavior)
 * agree on it without one importing the other's service.
 */
export const SCRATCH_DIR_NAME = "posthog-code-scratch";

/** Base directory for scratch dirs: a sibling of the worktree location. */
export function scratchBasePath(worktreeLocation: string): string {
  return path.join(path.dirname(worktreeLocation), SCRATCH_DIR_NAME);
}

/**
 * Whether a working directory lives under the scratch base (i.e. it's a
 * repo-less channel session, possibly cd'd into a cloned subdir). Checks an
 * actual path prefix against the real scratch base rather than just scanning
 * for the folder name, so an unrelated dir that happens to contain a
 * `posthog-code-scratch` segment can't spuriously enable channel mode.
 */
export function isScratchPath(
  workingDir: string,
  worktreeLocation: string,
): boolean {
  const base = path.resolve(scratchBasePath(worktreeLocation));
  const dir = path.resolve(workingDir);
  return dir === base || dir.startsWith(base + path.sep);
}
