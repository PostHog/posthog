import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { isScratchPath, SCRATCH_DIR_NAME, scratchBasePath } from "./scratch";

const worktreeLocation = path.join(os.tmpdir(), "managed", "worktrees");
const base = scratchBasePath(worktreeLocation);

describe("scratchBasePath", () => {
  it("is a sibling of the worktree location, not a child", () => {
    expect(path.dirname(base)).toBe(path.dirname(worktreeLocation));
    expect(path.basename(base)).toBe(SCRATCH_DIR_NAME);
    expect(base.startsWith(worktreeLocation + path.sep)).toBe(false);
  });
});

describe("isScratchPath", () => {
  it.each([
    { label: "the scratch base itself", dir: base, expected: true },
    {
      label: "a per-task scratch dir",
      dir: path.join(base, "task-1"),
      expected: true,
    },
    {
      label: "a repo cloned inside a scratch dir",
      dir: path.join(base, "task-1", "repos", "owner", "repo"),
      expected: true,
    },
    {
      label: "a sibling dir whose name shares the scratch prefix",
      dir: `${base}-evil`,
      expected: false,
    },
    {
      label: "the worktree location",
      dir: worktreeLocation,
      expected: false,
    },
    {
      label: "an unrelated path",
      dir: path.join(os.tmpdir(), "somewhere-else"),
      expected: false,
    },
  ])("returns $expected for $label", ({ dir, expected }) => {
    expect(isScratchPath(dir, worktreeLocation)).toBe(expected);
  });
});
