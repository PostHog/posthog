import type { GhExecResult } from "@posthog/git/gh";
import { beforeEach, describe, expect, it, vi } from "vitest";

const execGhMock = vi.hoisted(() => vi.fn());

vi.mock("@posthog/git/gh", () => ({ execGh: execGhMock }));

import { GitService } from "./service";

function ghResult(overrides: Partial<GhExecResult> = {}): GhExecResult {
  return {
    stdout: "",
    stderr: "",
    exitCode: 0,
    ...overrides,
  };
}

describe("GitService", () => {
  beforeEach(() => {
    execGhMock.mockReset();
  });

  it("returns no changed files when the remote branch does not exist yet", async () => {
    execGhMock
      .mockResolvedValueOnce(ghResult({ stdout: "main\n" }))
      .mockResolvedValueOnce(
        ghResult({
          stderr: "gh: Not Found (HTTP 404)\n",
          exitCode: 1,
        }),
      );

    await expect(
      new GitService().getBranchChangedFiles("posthog/code", "feature/new"),
    ).resolves.toEqual([]);
  });

  it("bounds GitHub pull request lookups so editor chips do not load forever", async () => {
    execGhMock.mockResolvedValue(
      ghResult({
        stdout: JSON.stringify({
          number: 123,
          title: "Fix pull request title resolution",
          state: "OPEN",
          url: "https://github.com/posthog/posthog/pull/123",
          isDraft: false,
        }),
      }),
    );

    await expect(
      new GitService().getGithubPullRequest("posthog", "posthog", 123),
    ).resolves.toMatchObject({
      number: 123,
      title: "Fix pull request title resolution",
    });

    expect(execGhMock).toHaveBeenCalledWith(
      [
        "pr",
        "view",
        "123",
        "--repo",
        "posthog/posthog",
        "--json",
        "number,title,state,url,isDraft",
      ],
      { timeoutMs: 10_000 },
    );
  });

  it("returns changed files from a successful comparison", async () => {
    execGhMock
      .mockResolvedValueOnce(ghResult({ stdout: "main\n" }))
      .mockResolvedValueOnce(
        ghResult({
          stdout: JSON.stringify({
            files: [
              {
                filename: "src/example.ts",
                status: "added",
                additions: 3,
                deletions: 0,
                sha: "abc123",
              },
            ],
          }),
        }),
      );

    await expect(
      new GitService().getBranchChangedFiles("posthog/code", "feature/new"),
    ).resolves.toEqual([
      {
        path: "src/example.ts",
        status: "added",
        originalPath: undefined,
        linesAdded: 3,
        linesRemoved: 0,
        sha: "abc123",
        patch: undefined,
      },
    ]);
  });

  it("preserves non-404 comparison failures", async () => {
    execGhMock
      .mockResolvedValueOnce(ghResult({ stdout: "main\n" }))
      .mockResolvedValueOnce(
        ghResult({
          stderr: "gh: authentication failed (HTTP 401)\n",
          exitCode: 1,
        }),
      );

    await expect(
      new GitService().getBranchChangedFiles("posthog/code", "feature/new"),
    ).rejects.toThrow("Failed to fetch branch files");
  });
});
