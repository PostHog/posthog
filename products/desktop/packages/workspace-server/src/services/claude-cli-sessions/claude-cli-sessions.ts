import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import {
  encodeCwdToProjectKey,
  getSessionJsonlPath,
} from "@posthog/agent/adapters/claude/session/jsonl-hydration";
import { mapWithConcurrency } from "@posthog/git/concurrency";
import { inject, injectable } from "inversify";
import { CLAUDE_SESSION_IMPORT_REPOSITORY } from "../../db/identifiers";
import type { IClaudeSessionImportRepository } from "../../db/repositories/claude-session-import-repository";
import type { ClaudeCliSessionsService } from "./identifiers";
import type {
  CliSessionFingerprint,
  CliSessionSummary,
  DeleteImportedCliSessionInput,
  DeleteImportRecordInput,
  ImportCliSessionInput,
  ImportCliSessionOutput,
  ListCliSessionsInput,
  ListCliSessionsOutput,
  RecordCliImportInput,
} from "./schemas";

// Bounds the head/tail reads per scan; stat-ing every file to sort by mtime is
// unaffected. Generous enough to surface a repo's full recent history while
// still capping work on pathological session counts.
const MAX_SESSIONS = 50;
const HEAD_BYTES = 16 * 1024;
const TAIL_BYTES = 64 * 1024;
const SCAN_CONCURRENCY = 8;

interface JsonlEntry {
  type?: string;
  cwd?: string;
  entrypoint?: string;
  uuid?: string;
  gitBranch?: string;
  aiTitle?: string;
  lastPrompt?: string;
}

interface ScannedSession {
  sourceSessionId: string;
  cwd: string;
  title: string | null;
  lastPrompt: string | null;
  mtimeMs: number;
  sizeBytes: number;
  gitBranch: string | null;
  lastEntryUuid: string | null;
}

function claudeCliDir(): string {
  return path.join(os.homedir(), ".claude");
}

/** Repo paths may arrive tilde-prefixed from the renderer. */
function expandHome(p: string): string {
  return p.startsWith("~") ? path.join(os.homedir(), p.slice(1)) : p;
}

function parseLines(chunk: string): JsonlEntry[] {
  const entries: JsonlEntry[] = [];
  for (const line of chunk.split("\n")) {
    if (!line.trim()) continue;
    try {
      entries.push(JSON.parse(line) as JsonlEntry);
    } catch {
      // Partial line at a chunk boundary, or corrupt — skip.
    }
  }
  return entries;
}

async function readSlice(
  filePath: string,
  start: number,
  length: number,
): Promise<string> {
  const handle = await fs.open(filePath, "r");
  try {
    const buffer = Buffer.alloc(length);
    const { bytesRead } = await handle.read(buffer, 0, length, start);
    return buffer.subarray(0, bytesRead).toString("utf-8");
  } finally {
    await handle.close();
  }
}

function isConversationEntry(entry: JsonlEntry): boolean {
  return entry.type === "user" || entry.type === "assistant";
}

@injectable()
export class ClaudeCliSessionsServiceImpl implements ClaudeCliSessionsService {
  constructor(
    @inject(CLAUDE_SESSION_IMPORT_REPOSITORY)
    private readonly importRepository: IClaudeSessionImportRepository,
  ) {}

  async listForRepo(
    input: ListCliSessionsInput,
  ): Promise<ListCliSessionsOutput> {
    const repoPath = expandHome(input.repoPath);
    const acceptedCwds = await this.acceptedCwds(repoPath);
    const projectDir = path.join(
      claudeCliDir(),
      "projects",
      encodeCwdToProjectKey(repoPath),
    );

    let fileNames: string[];
    try {
      const dirents = await fs.readdir(projectDir, { withFileTypes: true });
      fileNames = dirents
        .filter((d) => d.isFile() && d.name.endsWith(".jsonl"))
        .map((d) => d.name);
    } catch {
      // No CLI sessions recorded for this repo (or ~/.claude is absent).
      return { sessions: [] };
    }

    const stats = await mapWithConcurrency(
      fileNames,
      SCAN_CONCURRENCY,
      async (name) => {
        try {
          const stat = await fs.stat(path.join(projectDir, name));
          return { name, mtimeMs: stat.mtimeMs, sizeBytes: stat.size };
        } catch {
          return null;
        }
      },
    );

    const candidates = stats
      .filter((s): s is NonNullable<typeof s> => s !== null)
      .sort((a, b) => b.mtimeMs - a.mtimeMs)
      .slice(0, MAX_SESSIONS);

    const scanned = await mapWithConcurrency(
      candidates,
      SCAN_CONCURRENCY,
      (candidate) =>
        this.scanSessionFile(projectDir, candidate, acceptedCwds).catch(
          () => null,
        ),
    );

    const sessions = scanned.filter((s): s is ScannedSession => s !== null);
    return { sessions: this.withImportStatus(sessions) };
  }

  async importSession(
    input: ImportCliSessionInput,
  ): Promise<ImportCliSessionOutput> {
    const repoPath = expandHome(input.repoPath);
    const acceptedCwds = await this.acceptedCwds(repoPath);
    const sourcePath = path.join(
      claudeCliDir(),
      "projects",
      encodeCwdToProjectKey(repoPath),
      `${input.sourceSessionId}.jsonl`,
    );

    const stat = await fs.stat(sourcePath);
    const content = await fs.readFile(sourcePath, "utf-8");
    const importedSessionId = crypto.randomUUID();

    let cwdValidated = false;
    let lastEntryUuid: string | null = null;
    const rewritten: string[] = [];
    for (const line of content.split("\n")) {
      if (!line.trim()) continue;
      let entry: Record<string, unknown>;
      try {
        entry = JSON.parse(line) as Record<string, unknown>;
      } catch {
        rewritten.push(line);
        continue;
      }
      if (!cwdValidated && typeof entry.cwd === "string") {
        if (!acceptedCwds.has(entry.cwd)) {
          throw new Error(
            `Session ${input.sourceSessionId} belongs to ${entry.cwd}, not ${input.repoPath}`,
          );
        }
        // Mirror the listing filter: only a non-cli entrypoint disqualifies
        // (older CLI versions omit the field). Guards the public import
        // mutation against pulling in PostHog's own sdk-ts sessions.
        if (
          typeof entry.entrypoint === "string" &&
          entry.entrypoint !== "cli"
        ) {
          throw new Error(
            `Session ${input.sourceSessionId} is not a CLI session (entrypoint ${entry.entrypoint})`,
          );
        }
        cwdValidated = true;
      }
      if (typeof entry.uuid === "string") lastEntryUuid = entry.uuid;
      if ("sessionId" in entry) entry.sessionId = importedSessionId;
      rewritten.push(JSON.stringify(entry));
    }
    if (!cwdValidated) {
      throw new Error(
        `Session ${input.sourceSessionId} has no cwd entry for ${input.repoPath}`,
      );
    }

    const destPath = getSessionJsonlPath(importedSessionId, repoPath);
    await fs.mkdir(path.dirname(destPath), { recursive: true });
    const tmpPath = `${destPath}.tmp.${Date.now()}`;
    await fs.writeFile(tmpPath, `${rewritten.join("\n")}\n`);
    await fs.rename(tmpPath, destPath);

    await this.copyTaskSidecar(input.sourceSessionId, importedSessionId);

    return {
      importedSessionId,
      fingerprint: {
        sourceMtimeMs: Math.floor(stat.mtimeMs),
        sourceSizeBytes: stat.size,
        sourceLastEntryUuid: lastEntryUuid,
      },
    };
  }

  /**
   * Remove a copied transcript (and its task sidecar) from the app's config
   * dir. Used to compensate an import when task creation later rolls back, so
   * abandoned snapshots don't accumulate.
   */
  async deleteImportedSession(
    input: DeleteImportedCliSessionInput,
  ): Promise<void> {
    await this.removeSnapshotFiles(input.importedSessionId, input.repoPath);
  }

  /**
   * Compensate a deleted task: drop its import record and the copied snapshot
   * so the source session lists as `new` again (rather than `imported` with a
   * dangling task). No-op when the task was never an import.
   */
  async deleteImportForTask(taskId: string): Promise<void> {
    const row = this.importRepository.findByTaskId(taskId);
    if (!row) return;
    // Drop the row before the files: a later file-removal failure then leaves the
    // source `new` (re-importable, only leaking disk) instead of stuck `imported`.
    this.importRepository.deleteByTaskId(taskId);
    await this.removeSnapshotFiles(row.importedSessionId, row.repoPath);
  }

  /** Delete the imported transcript JSONL and its task sidecar, if present. */
  private async removeSnapshotFiles(
    importedSessionId: string,
    repoPath: string,
  ): Promise<void> {
    const transcriptPath = getSessionJsonlPath(
      importedSessionId,
      expandHome(repoPath),
    );
    await fs.rm(transcriptPath, { force: true });
    const configDir = process.env.CLAUDE_CONFIG_DIR;
    if (configDir) {
      await fs.rm(path.join(configDir, "tasks", importedSessionId), {
        recursive: true,
        force: true,
      });
    }
  }

  async recordImport(input: RecordCliImportInput): Promise<void> {
    this.importRepository.recordImport({
      sourceSessionId: input.sourceSessionId,
      importedSessionId: input.importedSessionId,
      taskId: input.taskId,
      repoPath: input.repoPath,
      sourceMtimeMs: input.fingerprint.sourceMtimeMs,
      sourceSizeBytes: input.fingerprint.sourceSizeBytes,
      sourceLastEntryUuid: input.fingerprint.sourceLastEntryUuid,
    });
  }

  /**
   * Inverse of `recordImport`: drop the tracking row for an imported snapshot.
   * Compensates the record step when task creation rolls back, so no row is
   * left pointing at a discarded task. Leaves the snapshot files alone — those
   * are owned by the import step's own compensation.
   */
  async deleteImportRecord(input: DeleteImportRecordInput): Promise<void> {
    this.importRepository.deleteByImportedSessionId(input.importedSessionId);
  }

  /** The repo path plus its realpath, so symlinked checkouts still match. */
  private async acceptedCwds(repoPath: string): Promise<Set<string>> {
    const accepted = new Set([repoPath]);
    try {
      accepted.add(await fs.realpath(repoPath));
    } catch {
      // Repo path may not resolve (e.g. in tests); the literal path suffices.
    }
    return accepted;
  }

  private async scanSessionFile(
    projectDir: string,
    candidate: { name: string; mtimeMs: number; sizeBytes: number },
    acceptedCwds: Set<string>,
  ): Promise<ScannedSession | null> {
    const filePath = path.join(projectDir, candidate.name);
    const head = parseLines(
      await readSlice(filePath, 0, Math.min(HEAD_BYTES, candidate.sizeBytes)),
    );

    const firstWithCwd = head.find((e) => typeof e.cwd === "string");
    if (!firstWithCwd?.cwd || !acceptedCwds.has(firstWithCwd.cwd)) return null;
    // PostHog's own sessions write entrypoint "sdk-ts"; older CLI
    // versions omit the field, so only a non-cli value disqualifies.
    if (firstWithCwd.entrypoint && firstWithCwd.entrypoint !== "cli") {
      return null;
    }

    // Reuse the head only when it already spans the whole file. The head
    // stops at HEAD_BYTES, so for any file larger than that we must read the
    // tail window (where the title/last-prompt/branch metadata lives) — for a
    // file up to TAIL_BYTES that window is the remainder of the file.
    const tailStart = Math.max(0, candidate.sizeBytes - TAIL_BYTES);
    const tail =
      candidate.sizeBytes <= HEAD_BYTES
        ? head
        : parseLines(
            await readSlice(
              filePath,
              tailStart,
              candidate.sizeBytes - tailStart,
            ),
          );

    if (![...head, ...tail].some(isConversationEntry)) return null;

    let title: string | null = null;
    let lastPrompt: string | null = null;
    let gitBranch: string | null = null;
    let lastEntryUuid: string | null = null;
    for (let i = tail.length - 1; i >= 0; i--) {
      const entry = tail[i] as JsonlEntry;
      if (title === null && entry.aiTitle) title = entry.aiTitle;
      if (lastPrompt === null && entry.lastPrompt) {
        lastPrompt = entry.lastPrompt;
      }
      if (gitBranch === null && entry.gitBranch) gitBranch = entry.gitBranch;
      if (lastEntryUuid === null && entry.uuid) lastEntryUuid = entry.uuid;
      if (title && lastPrompt && gitBranch && lastEntryUuid) break;
    }

    return {
      sourceSessionId: candidate.name.replace(/\.jsonl$/, ""),
      cwd: firstWithCwd.cwd,
      title,
      lastPrompt,
      mtimeMs: candidate.mtimeMs,
      sizeBytes: candidate.sizeBytes,
      gitBranch,
      lastEntryUuid,
    };
  }

  private withImportStatus(sessions: ScannedSession[]): CliSessionSummary[] {
    const rows = this.importRepository.listBySourceSessionIds(
      sessions.map((s) => s.sourceSessionId),
    );
    // Rows are sorted newest-first; keep the latest import per source.
    const latestBySource = new Map<string, (typeof rows)[number]>();
    for (const row of rows) {
      if (!latestBySource.has(row.sourceSessionId)) {
        latestBySource.set(row.sourceSessionId, row);
      }
    }

    return sessions.map((session) => {
      const row = latestBySource.get(session.sourceSessionId);
      let status: CliSessionSummary["status"] = "new";
      if (row) {
        const fingerprint: CliSessionFingerprint = {
          sourceMtimeMs: Math.floor(session.mtimeMs),
          sourceSizeBytes: session.sizeBytes,
          sourceLastEntryUuid: session.lastEntryUuid,
        };
        // Content-based divergence: size plus the last entry's uuid. mtime is
        // deliberately excluded — a touch with no content change (backups, git
        // operations, re-opening in the CLI) must not flip a session to
        // "updated". Appending a turn changes both signals; an in-place edit
        // changes the size.
        const unchanged =
          row.sourceSizeBytes === fingerprint.sourceSizeBytes &&
          row.sourceLastEntryUuid === fingerprint.sourceLastEntryUuid;
        status = unchanged ? "imported" : "updated";
      }
      return {
        sourceSessionId: session.sourceSessionId,
        cwd: session.cwd,
        title: session.title,
        lastPrompt: session.lastPrompt,
        updatedAt: new Date(session.mtimeMs).toISOString(),
        sizeBytes: session.sizeBytes,
        gitBranch: session.gitBranch,
        status,
        importedTaskId: row?.taskId ?? null,
      };
    });
  }

  private async copyTaskSidecar(
    sourceSessionId: string,
    importedSessionId: string,
  ): Promise<void> {
    const configDir = process.env.CLAUDE_CONFIG_DIR;
    if (!configDir) return;
    const sourceTasksDir = path.join(claudeCliDir(), "tasks", sourceSessionId);
    try {
      await fs.cp(
        sourceTasksDir,
        path.join(configDir, "tasks", importedSessionId),
        {
          recursive: true,
          errorOnExist: false,
          force: false,
        },
      );
    } catch {
      // Task sidecar is optional; the transcript alone is enough to resume.
    }
  }
}
