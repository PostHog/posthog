import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { encodeCwdToProjectKey } from "@posthog/agent/adapters/claude/session/jsonl-hydration";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { createMockClaudeSessionImportRepository } from "../../db/repositories/claude-session-import-repository.mock";
import { ClaudeCliSessionsServiceImpl } from "./claude-cli-sessions";

const SOURCE_SESSION_ID = "5e4f5423-0287-4473-ae06-24df41c62993";

let tmpDir: string;
let homeDir: string;
let configDir: string;
let repoPath: string;
let originalHome: string | undefined;
let originalConfigDir: string | undefined;
let importRepository: ReturnType<
  typeof createMockClaudeSessionImportRepository
>;
let service: ClaudeCliSessionsServiceImpl;

function cliProjectDir(): string {
  return path.join(
    homeDir,
    ".claude",
    "projects",
    encodeCwdToProjectKey(repoPath),
  );
}

function writeSessionFile(
  sessionId: string,
  lines: Record<string, unknown>[],
): string {
  const dir = cliProjectDir();
  fs.mkdirSync(dir, { recursive: true });
  const filePath = path.join(dir, `${sessionId}.jsonl`);
  fs.writeFileSync(
    filePath,
    `${lines.map((l) => JSON.stringify(l)).join("\n")}\n`,
  );
  return filePath;
}

function conversationLines(
  sessionId: string,
  overrides: { cwd?: string; entrypoint?: string } = {},
): Record<string, unknown>[] {
  const cwd = overrides.cwd ?? repoPath;
  const entrypoint = overrides.entrypoint ?? "cli";
  return [
    { type: "mode", mode: "normal", sessionId },
    {
      type: "user",
      uuid: "user-uuid-1",
      sessionId,
      cwd,
      entrypoint,
      gitBranch: "main",
      message: { role: "user", content: "hello" },
    },
    {
      type: "assistant",
      uuid: "assistant-uuid-1",
      sessionId,
      cwd,
      entrypoint,
      gitBranch: "main",
      message: { role: "assistant", content: "hi" },
    },
    { type: "ai-title", aiTitle: "Fix the login flow", sessionId },
    { type: "last-prompt", lastPrompt: "hello", sessionId },
  ];
}

function importedTranscriptPath(importedSessionId: string): string {
  return path.join(
    configDir,
    "projects",
    encodeCwdToProjectKey(repoPath),
    `${importedSessionId}.jsonl`,
  );
}

function importedSidecarPath(importedSessionId: string): string {
  return path.join(configDir, "tasks", importedSessionId);
}

async function importAndRecord(taskId = "task-1") {
  const imported = await service.importSession({
    repoPath,
    sourceSessionId: SOURCE_SESSION_ID,
  });
  await service.recordImport({
    sourceSessionId: SOURCE_SESSION_ID,
    importedSessionId: imported.importedSessionId,
    repoPath,
    taskId,
    fingerprint: imported.fingerprint,
  });
  return imported;
}

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "cli-sessions-test-"));
  homeDir = path.join(tmpDir, "home");
  configDir = path.join(tmpDir, "app-claude");
  repoPath = path.join(tmpDir, "repo");
  fs.mkdirSync(homeDir, { recursive: true });
  fs.mkdirSync(configDir, { recursive: true });
  fs.mkdirSync(repoPath, { recursive: true });

  originalHome = process.env.HOME;
  originalConfigDir = process.env.CLAUDE_CONFIG_DIR;
  process.env.HOME = homeDir;
  process.env.CLAUDE_CONFIG_DIR = configDir;

  importRepository = createMockClaudeSessionImportRepository();
  service = new ClaudeCliSessionsServiceImpl(importRepository);
});

afterEach(() => {
  process.env.HOME = originalHome;
  if (originalConfigDir === undefined) {
    delete process.env.CLAUDE_CONFIG_DIR;
  } else {
    process.env.CLAUDE_CONFIG_DIR = originalConfigDir;
  }
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe("listForRepo", () => {
  it("returns an empty list when ~/.claude does not exist", async () => {
    const result = await service.listForRepo({ repoPath });
    expect(result.sessions).toEqual([]);
  });

  it("lists a CLI session with metadata from the transcript", async () => {
    writeSessionFile(SOURCE_SESSION_ID, conversationLines(SOURCE_SESSION_ID));

    const result = await service.listForRepo({ repoPath });

    expect(result.sessions).toHaveLength(1);
    const session = result.sessions[0];
    expect(session?.sourceSessionId).toBe(SOURCE_SESSION_ID);
    expect(session?.title).toBe("Fix the login flow");
    expect(session?.lastPrompt).toBe("hello");
    expect(session?.gitBranch).toBe("main");
    expect(session?.status).toBe("new");
    expect(session?.importedTaskId).toBeNull();
  });

  it("skips sessions whose cwd does not match the repo", async () => {
    writeSessionFile(
      SOURCE_SESSION_ID,
      conversationLines(SOURCE_SESSION_ID, { cwd: "/somewhere/else" }),
    );

    const result = await service.listForRepo({ repoPath });
    expect(result.sessions).toEqual([]);
  });

  it("skips sessions with a non-cli entrypoint", async () => {
    writeSessionFile(
      SOURCE_SESSION_ID,
      conversationLines(SOURCE_SESSION_ID, { entrypoint: "sdk-ts" }),
    );

    const result = await service.listForRepo({ repoPath });
    expect(result.sessions).toEqual([]);
  });

  it("skips metadata-only files with no conversation", async () => {
    writeSessionFile(SOURCE_SESSION_ID, [
      { type: "mode", mode: "normal", sessionId: SOURCE_SESSION_ID },
      {
        type: "ai-title",
        aiTitle: "Empty",
        sessionId: SOURCE_SESSION_ID,
      },
    ]);

    const result = await service.listForRepo({ repoPath });
    expect(result.sessions).toEqual([]);
  });

  it("reads metadata at the end of a mid-sized (>16KB) transcript", async () => {
    // Pad the conversation so the file lands in the 16KB–64KB band, where the
    // head read stops short of the end. The title/last-prompt live on the final
    // lines, so the scan must read the tail window to surface them.
    const filler = Array.from({ length: 80 }, (_, i) => ({
      type: i % 2 === 0 ? "user" : "assistant",
      uuid: `filler-${i}`,
      sessionId: SOURCE_SESSION_ID,
      cwd: repoPath,
      entrypoint: "cli",
      gitBranch: "main",
      message: {
        role: i % 2 === 0 ? "user" : "assistant",
        content: "x".repeat(300),
      },
    }));
    const filePath = writeSessionFile(SOURCE_SESSION_ID, [
      { type: "mode", mode: "normal", sessionId: SOURCE_SESSION_ID },
      {
        type: "user",
        uuid: "user-uuid-1",
        sessionId: SOURCE_SESSION_ID,
        cwd: repoPath,
        entrypoint: "cli",
        gitBranch: "main",
        message: { role: "user", content: "hello" },
      },
      ...filler,
      { type: "ai-title", aiTitle: "Tail title", sessionId: SOURCE_SESSION_ID },
      {
        type: "last-prompt",
        lastPrompt: "final prompt",
        sessionId: SOURCE_SESSION_ID,
      },
    ]);
    const size = fs.statSync(filePath).size;
    expect(size).toBeGreaterThan(16 * 1024);
    expect(size).toBeLessThan(64 * 1024);

    const result = await service.listForRepo({ repoPath });

    expect(result.sessions).toHaveLength(1);
    expect(result.sessions[0]?.title).toBe("Tail title");
    expect(result.sessions[0]?.lastPrompt).toBe("final prompt");
  });

  it("orders sessions newest first", async () => {
    const olderId = "11111111-1111-4111-8111-111111111111";
    const newerId = "22222222-2222-4222-8222-222222222222";
    const olderPath = writeSessionFile(olderId, conversationLines(olderId));
    writeSessionFile(newerId, conversationLines(newerId));
    const past = new Date(Date.now() - 60_000);
    fs.utimesSync(olderPath, past, past);

    const result = await service.listForRepo({ repoPath });

    expect(result.sessions.map((s) => s.sourceSessionId)).toEqual([
      newerId,
      olderId,
    ]);
  });

  it("derives imported status when the source is unchanged", async () => {
    writeSessionFile(SOURCE_SESSION_ID, conversationLines(SOURCE_SESSION_ID));
    await importAndRecord();

    const result = await service.listForRepo({ repoPath });

    expect(result.sessions[0]?.status).toBe("imported");
    expect(result.sessions[0]?.importedTaskId).toBe("task-1");
  });

  it("derives updated status when the source changed after import", async () => {
    const filePath = writeSessionFile(
      SOURCE_SESSION_ID,
      conversationLines(SOURCE_SESSION_ID),
    );
    await importAndRecord();

    fs.appendFileSync(
      filePath,
      `${JSON.stringify({
        type: "user",
        uuid: "user-uuid-2",
        sessionId: SOURCE_SESSION_ID,
        cwd: repoPath,
        entrypoint: "cli",
        message: { role: "user", content: "more" },
      })}\n`,
    );

    const result = await service.listForRepo({ repoPath });

    expect(result.sessions[0]?.status).toBe("updated");
    expect(result.sessions[0]?.importedTaskId).toBe("task-1");
  });

  it("stays imported when only the mtime changes (no content change)", async () => {
    const filePath = writeSessionFile(
      SOURCE_SESSION_ID,
      conversationLines(SOURCE_SESSION_ID),
    );
    await importAndRecord();

    // Touch the file: bump mtime without touching its contents.
    const later = new Date(Date.now() + 60_000);
    fs.utimesSync(filePath, later, later);

    const result = await service.listForRepo({ repoPath });

    expect(result.sessions[0]?.status).toBe("imported");
  });
});

describe("importSession", () => {
  it("copies the transcript under a fresh session id, rewriting sessionId", async () => {
    writeSessionFile(SOURCE_SESSION_ID, conversationLines(SOURCE_SESSION_ID));

    const result = await service.importSession({
      repoPath,
      sourceSessionId: SOURCE_SESSION_ID,
    });

    expect(result.importedSessionId).not.toBe(SOURCE_SESSION_ID);
    const lines = fs
      .readFileSync(importedTranscriptPath(result.importedSessionId), "utf-8")
      .trim()
      .split("\n")
      .map((l) => JSON.parse(l) as { sessionId?: string });
    expect(lines.length).toBeGreaterThan(0);
    for (const line of lines) {
      if ("sessionId" in line) {
        expect(line.sessionId).toBe(result.importedSessionId);
      }
    }
  });

  it("leaves the source file untouched", async () => {
    const filePath = writeSessionFile(
      SOURCE_SESSION_ID,
      conversationLines(SOURCE_SESSION_ID),
    );
    const before = fs.readFileSync(filePath, "utf-8");

    await service.importSession({
      repoPath,
      sourceSessionId: SOURCE_SESSION_ID,
    });

    expect(fs.readFileSync(filePath, "utf-8")).toBe(before);
  });

  it("returns a fingerprint with the last entry uuid", async () => {
    writeSessionFile(SOURCE_SESSION_ID, conversationLines(SOURCE_SESSION_ID));

    const result = await service.importSession({
      repoPath,
      sourceSessionId: SOURCE_SESSION_ID,
    });

    expect(result.fingerprint.sourceLastEntryUuid).toBe("assistant-uuid-1");
    expect(result.fingerprint.sourceSizeBytes).toBeGreaterThan(0);
  });

  it("rejects sessions whose cwd does not match the repo", async () => {
    writeSessionFile(
      SOURCE_SESSION_ID,
      conversationLines(SOURCE_SESSION_ID, { cwd: "/somewhere/else" }),
    );

    await expect(
      service.importSession({ repoPath, sourceSessionId: SOURCE_SESSION_ID }),
    ).rejects.toThrow(/belongs to/);
  });

  it("rejects sessions with a non-cli entrypoint", async () => {
    writeSessionFile(
      SOURCE_SESSION_ID,
      conversationLines(SOURCE_SESSION_ID, { entrypoint: "sdk-ts" }),
    );

    await expect(
      service.importSession({ repoPath, sourceSessionId: SOURCE_SESSION_ID }),
    ).rejects.toThrow(/not a CLI session/);
  });

  it("copies the tasks sidecar under the imported session id", async () => {
    writeSessionFile(SOURCE_SESSION_ID, conversationLines(SOURCE_SESSION_ID));
    const tasksDir = path.join(homeDir, ".claude", "tasks", SOURCE_SESSION_ID);
    fs.mkdirSync(tasksDir, { recursive: true });
    fs.writeFileSync(path.join(tasksDir, "1.json"), JSON.stringify({ id: 1 }));

    const result = await service.importSession({
      repoPath,
      sourceSessionId: SOURCE_SESSION_ID,
    });

    const copied = path.join(
      importedSidecarPath(result.importedSessionId),
      "1.json",
    );
    expect(fs.existsSync(copied)).toBe(true);
  });
});

describe("deleteImportedSession", () => {
  it("removes the copied transcript and task sidecar", async () => {
    writeSessionFile(SOURCE_SESSION_ID, conversationLines(SOURCE_SESSION_ID));
    const tasksDir = path.join(homeDir, ".claude", "tasks", SOURCE_SESSION_ID);
    fs.mkdirSync(tasksDir, { recursive: true });
    fs.writeFileSync(path.join(tasksDir, "1.json"), JSON.stringify({ id: 1 }));

    const imported = await service.importSession({
      repoPath,
      sourceSessionId: SOURCE_SESSION_ID,
    });
    const transcriptPath = importedTranscriptPath(imported.importedSessionId);
    const sidecarPath = importedSidecarPath(imported.importedSessionId);
    expect(fs.existsSync(transcriptPath)).toBe(true);
    expect(fs.existsSync(sidecarPath)).toBe(true);

    await service.deleteImportedSession({
      repoPath,
      importedSessionId: imported.importedSessionId,
    });

    expect(fs.existsSync(transcriptPath)).toBe(false);
    expect(fs.existsSync(sidecarPath)).toBe(false);
  });

  it("does not throw when nothing was imported", async () => {
    await expect(
      service.deleteImportedSession({
        repoPath,
        importedSessionId: "33333333-3333-4333-8333-333333333333",
      }),
    ).resolves.toBeUndefined();
  });
});

describe("deleteImportForTask", () => {
  it("removes the snapshot and record so the source lists as new again", async () => {
    writeSessionFile(SOURCE_SESSION_ID, conversationLines(SOURCE_SESSION_ID));
    const imported = await importAndRecord();
    const transcriptPath = importedTranscriptPath(imported.importedSessionId);
    expect(fs.existsSync(transcriptPath)).toBe(true);
    const before = await service.listForRepo({ repoPath });
    expect(before.sessions[0]?.status).toBe("imported");

    await service.deleteImportForTask("task-1");

    expect(fs.existsSync(transcriptPath)).toBe(false);
    const after = await service.listForRepo({ repoPath });
    expect(after.sessions[0]?.status).toBe("new");
    expect(after.sessions[0]?.importedTaskId).toBeNull();
  });

  it("is a no-op for a task that was never imported", async () => {
    await expect(
      service.deleteImportForTask("unknown-task"),
    ).resolves.toBeUndefined();
  });
});

describe("deleteImportRecord", () => {
  it("drops the tracking row but leaves the snapshot files", async () => {
    writeSessionFile(SOURCE_SESSION_ID, conversationLines(SOURCE_SESSION_ID));
    const imported = await importAndRecord();
    const transcriptPath = importedTranscriptPath(imported.importedSessionId);
    expect((await service.listForRepo({ repoPath })).sessions[0]?.status).toBe(
      "imported",
    );

    await service.deleteImportRecord({
      importedSessionId: imported.importedSessionId,
    });

    // Row gone — source lists as new again — but the snapshot file remains,
    // since removing it is the import step's own compensation.
    const after = await service.listForRepo({ repoPath });
    expect(after.sessions[0]?.status).toBe("new");
    expect(after.sessions[0]?.importedTaskId).toBeNull();
    expect(fs.existsSync(transcriptPath)).toBe(true);
  });

  it("is a no-op when no row matches the imported session id", async () => {
    await expect(
      service.deleteImportRecord({
        importedSessionId: "44444444-4444-4444-8444-444444444444",
      }),
    ).resolves.toBeUndefined();
  });
});
