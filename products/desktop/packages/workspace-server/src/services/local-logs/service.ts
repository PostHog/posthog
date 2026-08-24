import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { injectable } from "inversify";

import type { ILogsService } from "./identifiers";

const DATA_DIR = ".posthog-code";

const TOOL_CALL_UPDATE_MARKER = '"sessionUpdate":"tool_call_update"';

interface StoredEntryShape {
  notification?: {
    params?: Record<string, unknown>;
  } & Record<string, unknown>;
}

function toolCallUpdateOfLine(
  line: string,
): { entry: StoredEntryShape; update: Record<string, unknown> } | null {
  // Substring pre-filter: an unescaped marker can only occur as JSON
  // structure (a quote inside a string value is always escaped), so
  // non-matching lines are skipped without parsing.
  if (!line.includes(TOOL_CALL_UPDATE_MARKER)) return null;
  let entry: StoredEntryShape;
  try {
    entry = JSON.parse(line) as StoredEntryShape;
  } catch {
    return null;
  }
  const update = entry?.notification?.params?.update as
    | Record<string, unknown>
    | undefined;
  if (update?.sessionUpdate !== "tool_call_update") return null;
  if (typeof update.toolCallId !== "string") return null;
  return { entry, update };
}

/**
 * Collapse superseded `tool_call_update` lines into one merged line per
 * `toolCallId` (at the last update's position) before the log crosses to the
 * renderer. Agents re-send the full accumulated tool output on every update,
 * so the transfer + parse would otherwise carry hundreds of MB of redundant
 * snapshots.
 *
 * Updates are merged (shallow, later fields win) rather than dropped: they
 * carry different fields at different times (streamed `rawInput` snapshots,
 * input-derived title/content, edit diffs, terminal status/rawOutput) and the
 * renderer reducer `Object.assign`s each one, so a merged update reproduces
 * exactly what replaying every line would build. Only `tool_call_update`
 * lines are parsed; other lines pass through untouched, so the result stays
 * valid NDJSON. Parsing those lines here trades one pass of workspace-server
 * CPU for not shipping and parsing the same bytes in the renderer.
 */
function collapseToolCallUpdateLines(ndjson: string): string {
  const lines = ndjson.split("\n");
  const idByIndex = new Array<string | undefined>(lines.length);
  const firstIndexById = new Map<string, number>();
  const lastIndexById = new Map<string, number>();
  const lastEntryById = new Map<string, StoredEntryShape>();
  const mergedById = new Map<string, Record<string, unknown>>();

  for (let i = 0; i < lines.length; i++) {
    const parsed = toolCallUpdateOfLine(lines[i]);
    if (!parsed) continue;
    const id = parsed.update.toolCallId as string;
    idByIndex[i] = id;
    lastIndexById.set(id, i);
    lastEntryById.set(id, parsed.entry);
    const merged = mergedById.get(id);
    if (merged) {
      Object.assign(merged, parsed.update);
    } else {
      firstIndexById.set(id, i);
      mergedById.set(id, { ...parsed.update });
    }
  }
  if (lastIndexById.size === 0) return ndjson;

  const kept: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    const id = idByIndex[i];
    if (id === undefined) {
      kept.push(lines[i]);
      continue;
    }
    if (lastIndexById.get(id) !== i) continue;
    if (firstIndexById.get(id) === i) {
      // Single update for this call: the original line already is the merge.
      kept.push(lines[i]);
      continue;
    }
    const entry = lastEntryById.get(id);
    const merged = mergedById.get(id);
    if (!entry || !merged) {
      kept.push(lines[i]);
      continue;
    }
    kept.push(
      JSON.stringify({
        ...entry,
        notification: {
          ...entry.notification,
          params: { ...entry.notification?.params, update: merged },
        },
      }),
    );
  }
  return kept.join("\n");
}

interface WriteState {
  pending: string | undefined;
  lastWritten: string | undefined;
  dirReady: boolean;
}

/**
 * Single-flight per `taskRunId` with latest-wins coalescing. Prevents the
 * gap-reconcile loop from spawning parallel writeFile of the same NDJSON.
 */
@injectable()
export class LocalLogsService implements ILogsService {
  private writes = new Map<
    string,
    { state: WriteState; inFlight: Promise<void> }
  >();

  async fetchS3Logs(logUrl: string): Promise<string | null> {
    try {
      const response = await fetch(logUrl);
      if (response.status === 404) {
        return null;
      }
      if (!response.ok) {
        return null;
      }
      return await response.text();
    } catch {
      return null;
    }
  }

  async readLocalLogs(taskRunId: string): Promise<string | null> {
    const logPath = this.getLocalLogPath(taskRunId);
    try {
      return await fs.promises.readFile(logPath, "utf-8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        return null;
      }
      return null;
    }
  }

  async readLocalLogsCollapsed(
    taskRunId: string,
  ): Promise<{ content: string; totalLineCount: number } | null> {
    const raw = await this.readLocalLogs(taskRunId);
    if (raw === null) return null;
    const trimmed = raw.trim();
    const totalLineCount = trimmed ? trimmed.split("\n").length : 0;
    return { content: collapseToolCallUpdateLines(raw), totalLineCount };
  }

  async readLocalLogsTail(
    taskRunId: string,
    maxBytes: number,
  ): Promise<{ content: string; truncated: boolean } | null> {
    const logPath = this.getLocalLogPath(taskRunId);
    try {
      const stat = await fs.promises.stat(logPath);
      if (stat.size <= maxBytes) {
        return {
          content: await fs.promises.readFile(logPath, "utf-8"),
          truncated: false,
        };
      }
      const handle = await fs.promises.open(logPath, "r");
      try {
        // Read one extra byte before the window: a newline there means the
        // window already starts on a whole line. Otherwise the first line is
        // a fragment (and may start with a broken multi-byte char) — drop
        // everything up to the first newline so only whole ndjson lines
        // remain.
        const start = stat.size - maxBytes - 1;
        const buf = Buffer.alloc(maxBytes + 1);
        const { bytesRead } = await handle.read(buf, 0, maxBytes + 1, start);
        const raw = buf.toString("utf-8", 1, bytesRead);
        if (buf[0] === 0x0a) {
          return { content: raw, truncated: true };
        }
        const nl = raw.indexOf("\n");
        return { content: nl >= 0 ? raw.slice(nl + 1) : "", truncated: true };
      } finally {
        await handle.close();
      }
    } catch {
      return null;
    }
  }

  writeLocalLogs(taskRunId: string, content: string): Promise<void> {
    const existing = this.writes.get(taskRunId);
    if (existing) {
      existing.state.pending = content;
      return existing.inFlight;
    }

    const state: WriteState = {
      pending: undefined,
      lastWritten: undefined,
      dirReady: false,
    };
    const inFlight = this.drain(taskRunId, content, state);
    this.writes.set(taskRunId, { state, inFlight });
    return inFlight;
  }

  async seedLocalLogs(taskRunId: string, content: string): Promise<void> {
    if (!content?.trim()) return;
    const logPath = this.getLocalLogPath(taskRunId);
    const marker = JSON.stringify({ type: "seed_boundary" });
    const trailingNewline = content.endsWith("\n") ? "" : "\n";
    await fs.promises.mkdir(path.dirname(logPath), { recursive: true });
    await fs.promises.writeFile(
      logPath,
      `${content}${trailingNewline}${marker}\n`,
      "utf-8",
    );
  }

  async countLocalLogEntries(taskRunId: string): Promise<number> {
    const logPath = this.getLocalLogPath(taskRunId);
    try {
      const content = await fs.promises.readFile(logPath, "utf-8");
      return content.split("\n").filter((line) => line.trim()).length;
    } catch {
      return 0;
    }
  }

  async deleteLocalLogCache(taskRunId: string): Promise<void> {
    const logPath = this.getLocalLogPath(taskRunId);
    await fs.promises.rm(logPath, { force: true });
  }

  private async drain(
    taskRunId: string,
    initialContent: string,
    state: WriteState,
  ): Promise<void> {
    try {
      let next: string | undefined = initialContent;
      while (next !== undefined) {
        const current = next;
        next = undefined;
        if (current !== state.lastWritten) {
          await this.doWrite(taskRunId, current, state);
          state.lastWritten = current;
        }
        if (state.pending !== undefined) {
          next = state.pending;
          state.pending = undefined;
        }
      }
    } finally {
      this.writes.delete(taskRunId);
    }
  }

  private async doWrite(
    taskRunId: string,
    content: string,
    state: WriteState,
  ): Promise<void> {
    const logPath = this.getLocalLogPath(taskRunId);
    try {
      if (!state.dirReady) {
        await fs.promises.mkdir(path.dirname(logPath), { recursive: true });
        state.dirReady = true;
      }
      await fs.promises.writeFile(logPath, content, "utf-8");
    } catch {}
  }

  private getLocalLogPath(taskRunId: string): string {
    return path.join(
      os.homedir(),
      DATA_DIR,
      "sessions",
      taskRunId,
      "logs.ndjson",
    );
  }
}
