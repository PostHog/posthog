import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { recoverArchiveDetailsFromLogs } from "./archive-recovery";

const TASK_ID = "f7c8ae0f-0022-405e-8e36-da28c0f2c268";
let tempDir: string | null = null;

afterEach(async () => {
  if (tempDir) await fs.rm(tempDir, { recursive: true, force: true });
  tempDir = null;
});

describe("recoverArchiveDetailsFromLogs", () => {
  it("recovers archive details from the first prompt", async () => {
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "archive-recovery-"));
    const runDir = path.join(tempDir, "run-id");
    await fs.mkdir(runDir);
    await fs.writeFile(
      path.join(runDir, "logs.ndjson"),
      [
        JSON.stringify({
          notification: {
            method: "session/new",
            params: {
              cwd: "/repos/posthog-code",
              _meta: {
                systemPrompt: { append: `instructions\nTask-Id: ${TASK_ID}` },
              },
            },
          },
        }),
        JSON.stringify({
          timestamp: "2026-07-22T19:00:00.000Z",
          notification: {
            method: "session/prompt",
            params: {
              prompt: [
                { type: "text", text: "Recover this task\nMore detail" },
              ],
            },
          },
        }),
      ].join("\n"),
    );

    await expect(
      recoverArchiveDetailsFromLogs(new Set([TASK_ID]), tempDir),
    ).resolves.toEqual([
      {
        taskId: TASK_ID,
        title: "Recover this task",
        taskCreatedAt: "2026-07-22T19:00:00.000Z",
        repository: "/repos/posthog-code",
      },
    ]);
  });

  it("recovers repository identity when the prompt is missing", async () => {
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "archive-recovery-"));
    const runDir = path.join(tempDir, "run-id");
    await fs.mkdir(runDir);
    await fs.writeFile(
      path.join(runDir, "logs.ndjson"),
      JSON.stringify({
        timestamp: "2026-07-22T19:00:00.000Z",
        notification: {
          method: "session/new",
          params: {
            cwd: "/repos/posthog-code",
            _meta: {
              systemPrompt: { append: `instructions\nTask-Id: ${TASK_ID}` },
            },
          },
        },
      }),
    );

    await expect(
      recoverArchiveDetailsFromLogs(new Set([TASK_ID]), tempDir),
    ).resolves.toEqual([
      {
        taskId: TASK_ID,
        title: `Unknown task (${TASK_ID.slice(0, 8)})`,
        taskCreatedAt: "2026-07-22T19:00:00.000Z",
        repository: "/repos/posthog-code",
      },
    ]);
  });
});
