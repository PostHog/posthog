import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";

export interface RecoveredArchiveDetails {
  taskId: string;
  title: string;
  taskCreatedAt: string | null;
  repository: string | null;
}

interface LogEntry {
  timestamp?: string;
  notification?: {
    method?: string;
    params?: {
      cwd?: string;
      prompt?: Array<{ type?: string; text?: string }>;
      _meta?: { systemPrompt?: { append?: string } };
    };
  };
}

const TASK_ID_PATTERN = /Task-Id:\s*([0-9a-f-]{36})/i;

export async function recoverArchiveDetailsFromLogs(
  requestedTaskIds: ReadonlySet<string>,
  sessionsDir = path.join(os.homedir(), ".posthog-code", "sessions"),
): Promise<RecoveredArchiveDetails[]> {
  let taskIds = requestedTaskIds;
  if (taskIds.size === 0) return [];
  const recovered: RecoveredArchiveDetails[] = [];
  const directories = await fs.promises
    .readdir(sessionsDir, { withFileTypes: true })
    .catch(() => []);

  for (const directory of directories) {
    if (!directory.isDirectory()) continue;
    const details = await recoverFromLog(
      path.join(sessionsDir, directory.name, "logs.ndjson"),
      taskIds,
    );
    if (!details) continue;
    recovered.push(details);
    taskIds = new Set([...taskIds].filter((id) => id !== details.taskId));
    if (taskIds.size === 0) break;
  }
  return recovered;
}

async function recoverFromLog(
  logPath: string,
  taskIds: ReadonlySet<string>,
): Promise<RecoveredArchiveDetails | null> {
  const stream = fs.createReadStream(logPath, { encoding: "utf8" });
  stream.on("error", () => {});
  const lines = readline.createInterface({
    input: stream,
    crlfDelay: Infinity,
  });
  let taskId: string | null = null;
  let repository: string | null = null;
  let sessionStartedAt: string | null = null;

  try {
    for await (const line of lines) {
      let entry: LogEntry;
      try {
        entry = JSON.parse(line) as LogEntry;
      } catch {
        continue;
      }
      const params = entry.notification?.params;
      if (!taskId && entry.notification?.method === "session/new") {
        const candidate =
          params?._meta?.systemPrompt?.append?.match(TASK_ID_PATTERN)?.[1];
        if (!candidate || !taskIds.has(candidate)) return null;
        taskId = candidate;
        repository = params?.cwd ?? null;
        sessionStartedAt = entry.timestamp ?? null;
      }
      if (taskId && entry.notification?.method === "session/prompt") {
        const title = params?.prompt
          ?.find((block) => block.type === "text")
          ?.text?.trim();
        if (!title) continue;
        return {
          taskId,
          title: title.split("\n")[0].slice(0, 200),
          taskCreatedAt: entry.timestamp ?? null,
          repository,
        };
      }
    }
  } catch {
    return null;
  } finally {
    lines.close();
    stream.destroy();
  }
  return taskId
    ? {
        taskId,
        title: `Unknown task (${taskId.slice(0, 8)})`,
        taskCreatedAt: sessionStartedAt,
        repository,
      }
    : null;
}
