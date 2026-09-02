import { vol } from "memfs";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("node:fs/promises", async () => {
  const { fs } = await import("memfs");
  return { ...fs.promises, default: fs.promises };
});

import { getBranchFromPath, hasAnyFiles } from "./repo-fs-query";

afterEach(() => {
  vol.reset();
});

describe("hasAnyFiles", () => {
  it("is true when the repo has a tracked file alongside .git", async () => {
    vol.fromJSON({ "/repo/.git/HEAD": "x", "/repo/README.md": "hi" });

    expect(await hasAnyFiles("/repo")).toBe(true);
  });

  it("is false when the repo contains only .git", async () => {
    vol.fromJSON({ "/repo/.git/HEAD": "x" });

    expect(await hasAnyFiles("/repo")).toBe(false);
  });

  it("is false when the path does not exist", async () => {
    expect(await hasAnyFiles("/nope")).toBe(false);
  });
});

describe("getBranchFromPath", () => {
  it("reads the branch from a .git directory HEAD", async () => {
    vol.fromJSON({ "/repo/.git/HEAD": "ref: refs/heads/main\n" });

    expect(await getBranchFromPath("/repo")).toBe("main");
  });

  it("returns null for a detached HEAD (no ref line)", async () => {
    vol.fromJSON({ "/repo/.git/HEAD": "9f1c2d3e4b5a6\n" });

    expect(await getBranchFromPath("/repo")).toBeNull();
  });

  it("follows a worktree .git file gitdir pointer to its HEAD", async () => {
    vol.fromJSON({
      "/repo/.worktrees/feat/.git": "gitdir: /repo/.git/worktrees/feat\n",
      "/repo/.git/worktrees/feat/HEAD": "ref: refs/heads/feat\n",
    });

    expect(await getBranchFromPath("/repo/.worktrees/feat")).toBe("feat");
  });

  it("returns null when the .git file has no gitdir pointer", async () => {
    vol.fromJSON({ "/repo/.worktrees/x/.git": "garbage\n" });

    expect(await getBranchFromPath("/repo/.worktrees/x")).toBeNull();
  });

  it("returns null when the path is not a git repo", async () => {
    vol.fromJSON({ "/plain/file.txt": "hi" });

    expect(await getBranchFromPath("/plain")).toBeNull();
  });
});
