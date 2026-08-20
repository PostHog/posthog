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

  it("returns lifecycle and creator details for a pull request", async () => {
    const details = {
      state: "open",
      merged: false,
      draft: false,
      headRefName: "posthog/status-chip",
      title: "Show pull request status in sessions",
      author: "octocat",
    };
    execGhMock.mockResolvedValueOnce(
      ghResult({ stdout: JSON.stringify(details) }),
    );

    await expect(
      new GitService().getPrDetailsByUrl(
        "https://github.com/PostHog/posthog/pull/23985",
      ),
    ).resolves.toEqual(details);
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

  it("maps a commit's files, including removals and renames", async () => {
    execGhMock.mockResolvedValueOnce(
      ghResult({
        stdout: JSON.stringify({
          files: [
            {
              filename: "docs/old.md",
              status: "removed",
              additions: 0,
              deletions: 7,
            },
            {
              filename: "src/new-name.ts",
              status: "renamed",
              previous_filename: "src/old-name.ts",
              additions: 1,
              deletions: 1,
            },
          ],
        }),
      }),
    );

    await expect(
      new GitService().getCommitChangedFiles("posthog/code", "a".repeat(40)),
    ).resolves.toEqual([
      {
        path: "docs/old.md",
        status: "deleted",
        originalPath: undefined,
        linesAdded: 0,
        linesRemoved: 7,
        sha: undefined,
        patch: undefined,
      },
      {
        path: "src/new-name.ts",
        status: "renamed",
        originalPath: "src/old-name.ts",
        linesAdded: 1,
        linesRemoved: 1,
        sha: undefined,
        patch: undefined,
      },
    ]);
    expect(execGhMock).toHaveBeenCalledWith(
      ["api", `repos/posthog/code/commits/${"a".repeat(40)}`],
      { timeoutMs: 10_000 },
    );
  });

  it("returns no commit files for an unknown sha, and never queries with a malformed one", async () => {
    execGhMock.mockResolvedValueOnce(
      ghResult({ stderr: "gh: Not Found (HTTP 404)\n", exitCode: 1 }),
    );
    await expect(
      new GitService().getCommitChangedFiles("posthog/code", "b".repeat(40)),
    ).resolves.toEqual([]);

    execGhMock.mockClear();
    await expect(
      new GitService().getCommitChangedFiles("posthog/code", "main..evil"),
    ).resolves.toEqual([]);
    expect(execGhMock).not.toHaveBeenCalled();
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

  it("keeps review threads whose author account was deleted", async () => {
    execGhMock.mockResolvedValueOnce(
      ghResult({
        stdout: JSON.stringify({
          data: {
            repository: {
              pullRequest: {
                reviewThreads: {
                  pageInfo: { hasNextPage: false, endCursor: null },
                  nodes: [
                    {
                      id: "thread-1",
                      isResolved: false,
                      isOutdated: false,
                      path: "src/example.ts",
                      diffSide: "RIGHT",
                      line: 4,
                      originalLine: 4,
                      startLine: null,
                      startDiffSide: null,
                      subjectType: "LINE",
                      comments: {
                        nodes: [
                          {
                            databaseId: 42,
                            body: "Still relevant",
                            path: "src/example.ts",
                            diffHunk: "@@ -1 +1 @@",
                            replyTo: null,
                            author: null,
                            createdAt: "2026-08-07T00:00:00Z",
                            updatedAt: "2026-08-07T00:00:00Z",
                          },
                        ],
                      },
                    },
                  ],
                },
              },
            },
          },
        }),
      }),
    );

    const threads = await new GitService().getPrReviewComments(
      "https://github.com/PostHog/posthog/pull/78690",
    );

    expect(threads[0]?.comments[0]?.user).toEqual({
      login: "ghost",
      avatar_url: "",
      isBot: false,
    });
  });
});
