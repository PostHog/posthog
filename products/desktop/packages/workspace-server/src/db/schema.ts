import { sql } from "drizzle-orm";
import { index, integer, sqliteTable, text } from "drizzle-orm/sqlite-core";

const id = () =>
  text()
    .primaryKey()
    .$defaultFn(() => crypto.randomUUID());

const createdAt = () => text().notNull().default(sql`(CURRENT_TIMESTAMP)`);
const updatedAt = () => text().notNull().default(sql`(CURRENT_TIMESTAMP)`);

export const repositories = sqliteTable("repositories", {
  id: id(),
  path: text().notNull().unique(),
  remoteUrl: text(),
  lastAccessedAt: text(),
  createdAt: createdAt(),
  updatedAt: updatedAt(),
});

export const workspaces = sqliteTable(
  "workspaces",
  {
    id: id(),
    taskId: text().notNull().unique(),
    repositoryId: text().references(() => repositories.id, {
      onDelete: "set null",
    }),
    mode: text({ enum: ["cloud", "local", "worktree"] }).notNull(),
    linkedBranch: text(),
    pinnedAt: text(),
    lastViewedAt: text(),
    lastActivityAt: text(),
    /** JSON-encoded array of absolute paths the agent can access for this task. */
    additionalDirectories: text().notNull().default("[]"),
    /** Cached PR URL for this task so task switches render without waiting on `gh`. */
    prUrl: text(),
    /** Cached PR state — values match the `SidebarPrState` union (open/merged/closed/draft). */
    prState: text({ enum: ["open", "merged", "closed", "draft"] }),
    prUrls: text().notNull().default("[]"),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [index("workspaces_repository_id_idx").on(t.repositoryId)],
);

// Pin / view / activity metadata for tasks that have no `workspaces` row —
// repo-less channel tasks (e.g. canvas generation) whose working dir is a
// scratch dir, not a tracked workspace. Tasks WITH a workspace row keep this
// metadata on their workspace row; this table is the fallback home so the
// per-device viewed/pinned state survives reload for the rowless ones too.
export const taskMetadata = sqliteTable("task_metadata", {
  taskId: text().primaryKey(),
  pinnedAt: text(),
  lastViewedAt: text(),
  lastActivityAt: text(),
  // Archive state for rowless tasks. Tasks WITH a `workspaces` row record their
  // archived state in the `archives` table; rowless channel tasks have no such
  // row, so this timestamp is their only home — without it, archiving them is a
  // silent no-op and they reappear on the next refetch.
  archivedAt: text(),
  archivedTitle: text(),
  archivedTaskCreatedAt: text(),
  archivedRepository: text(),
  piSessionFile: text(),
  createdAt: createdAt(),
  updatedAt: updatedAt(),
});

// Autoresearch runs, persisted so the optimization loop survives app
// restarts. `data` is the core AutoresearchRun serialized as JSON — the
// schema lives in @posthog/core; this table only indexes it. `endedAt` is
// null while a run is still open (running / paused / interrupted), which is
// what boot-time restore queries on.
export const autoresearchRuns = sqliteTable(
  "autoresearch_runs",
  {
    id: text().primaryKey(),
    taskId: text().notNull(),
    endedAt: text(),
    data: text().notNull(),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [index("autoresearch_runs_task_id_idx").on(t.taskId)],
);

export const worktrees = sqliteTable("worktrees", {
  id: id(),
  workspaceId: text()
    .notNull()
    .unique()
    .references(() => workspaces.id, { onDelete: "cascade" }),
  name: text().notNull(),
  path: text().notNull(),
  createdAt: createdAt(),
  updatedAt: updatedAt(),
});

export const archives = sqliteTable("archives", {
  id: id(),
  workspaceId: text()
    .notNull()
    .unique()
    .references(() => workspaces.id, { onDelete: "cascade" }),
  branchName: text(),
  checkpointId: text(),
  title: text(),
  taskCreatedAt: text(),
  repository: text(),
  archivedAt: text().notNull(),
  createdAt: createdAt(),
  updatedAt: updatedAt(),
});

export const suspensions = sqliteTable("suspensions", {
  id: id(),
  workspaceId: text()
    .notNull()
    .unique()
    .references(() => workspaces.id, { onDelete: "cascade" }),
  branchName: text(),
  checkpointId: text(),
  suspendedAt: text().notNull(),
  reason: text({
    enum: ["max_worktrees", "inactivity", "manual"],
  }).notNull(),
  createdAt: createdAt(),
  updatedAt: updatedAt(),
});

export const authSessions = sqliteTable("auth_sessions", {
  id: integer().primaryKey(),
  refreshTokenEncrypted: text().notNull(),
  cloudRegion: text({ enum: ["us", "eu", "dev"] }).notNull(),
  selectedProjectId: integer(),
  scopeVersion: integer().notNull(),
  createdAt: createdAt(),
  updatedAt: updatedAt(),
});

export const defaultAdditionalDirectories = sqliteTable(
  "default_additional_directories",
  {
    path: text().primaryKey(),
    createdAt: createdAt(),
  },
);

export const claudeSessionImports = sqliteTable(
  "claude_session_imports",
  {
    id: id(),
    /** Session id of the original Claude Code CLI session in ~/.claude. */
    sourceSessionId: text().notNull(),
    /** Fresh session id the imported snapshot lives under in CLAUDE_CONFIG_DIR. */
    importedSessionId: text().notNull().unique(),
    taskId: text().notNull(),
    repoPath: text().notNull(),
    /** Fingerprint of the source file at import time, for divergence detection. */
    sourceMtimeMs: integer().notNull(),
    sourceSizeBytes: integer().notNull(),
    sourceLastEntryUuid: text(),
    createdAt: createdAt(),
  },
  (t) => [
    index("claude_session_imports_source_idx").on(t.sourceSessionId),
    index("claude_session_imports_task_idx").on(t.taskId),
  ],
);

export const authPreferences = sqliteTable(
  "auth_preferences",
  {
    accountKey: text().notNull(),
    cloudRegion: text({ enum: ["us", "eu", "dev"] }).notNull(),
    lastSelectedProjectId: integer(),
    lastSelectedOrgId: text(),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [
    index("auth_preferences_account_region_idx").on(
      t.accountKey,
      t.cloudRegion,
    ),
  ],
);

export const authOrgProjectPreferences = sqliteTable(
  "auth_org_project_preferences",
  {
    accountKey: text().notNull(),
    cloudRegion: text({ enum: ["us", "eu", "dev"] }).notNull(),
    orgId: text().notNull(),
    lastSelectedProjectId: integer().notNull(),
    createdAt: createdAt(),
    updatedAt: updatedAt(),
  },
  (t) => [
    index("auth_org_project_account_region_org_idx").on(
      t.accountKey,
      t.cloudRegion,
      t.orgId,
    ),
  ],
);

/**
 * Windows holding browser-tab strips in the Channels canvas surface. One row
 * per OS window (or web window). The primary window is never torn down by
 * closing its last tab; secondaries are.
 */
export const browserWindows = sqliteTable("browser_windows", {
  id: id(),
  isPrimary: integer({ mode: "boolean" }).notNull().default(false),
  /** Saved geometry for session restore, JSON {x,y,width,height}. Null on web. */
  bounds: text({ mode: "json" }).$type<{
    x: number;
    y: number;
    width: number;
    height: number;
  } | null>(),
  /** Focused tab in this window; null = channels landing. */
  activeTabId: text(),
  /** Ordering across windows for deterministic restore. */
  position: integer().notNull().default(0),
  /** Epoch ms. */
  createdAt: integer().notNull(),
  updatedAt: integer().notNull(),
});

/**
 * Open tabs in the Channels canvas surface. A tab references a canvas
 * (dashboard) and the channel it belongs to; display is resolved at render.
 * `scrollState` is reserved/unwired for later per-tab state (scroll restore).
 */
export const browserTabs = sqliteTable(
  "browser_tabs",
  {
    id: id(),
    windowId: text()
      .notNull()
      .references(() => browserWindows.id, { onDelete: "cascade" }),
    /** Canvas this tab shows. Null for a task tab or a blank tab. */
    dashboardId: text(),
    /** Task this tab shows. Null for a canvas tab or a blank tab. */
    taskId: text(),
    channelId: text(),
    /** Channel sub-section (inbox/artifacts/history/context). Null = channel
     * home, or a non-channel tab. */
    channelSection: text(),
    /** Top-level app page (inbox/agents/skills/mcp-servers/command-center/home).
     * Null = a canvas / task / channel / blank tab. */
    appView: text(),
    /** Gap-spaced ordering key within a window. */
    position: integer().notNull(),
    /** Reserved/unwired. Opaque JSON for future per-tab state. */
    scrollState: text({ mode: "json" }).$type<unknown>(),
    /** Epoch ms. */
    createdAt: integer().notNull(),
    lastActiveAt: integer().notNull(),
  },
  (t) => [index("browser_tabs_window_idx").on(t.windowId)],
);
