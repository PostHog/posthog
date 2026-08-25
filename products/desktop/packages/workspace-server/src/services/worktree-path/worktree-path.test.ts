import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { deriveWorktreePath } from "./worktree-path";

const REPO = "/repos/posthog";
const REPO_NAME = "posthog";
const NAME = "plucky-summit-59";

describe("deriveWorktreePath", () => {
  let tmpDir: string;

  beforeEach(async () => {
    tmpDir = await fsp.mkdtemp(path.join(os.tmpdir(), "wt-helpers-"));
  });

  afterEach(async () => {
    await fsp.rm(tmpDir, { recursive: true, force: true });
  });

  it.each([
    {
      label: "new layout when it exists on disk",
      create: (base: string) => path.join(base, NAME, REPO_NAME),
      expected: (base: string) => path.join(base, NAME, REPO_NAME),
    },
    {
      label: "legacy layout when only it exists",
      create: (base: string) => path.join(base, REPO_NAME, NAME),
      expected: (base: string) => path.join(base, REPO_NAME, NAME),
    },
    {
      label: "new layout by default when neither exists (creation case)",
      create: () => null,
      expected: (base: string) => path.join(base, NAME, REPO_NAME),
    },
  ])("resolves the $label", async ({ create, expected }) => {
    const dir = create(tmpDir);
    if (dir) await fsp.mkdir(dir, { recursive: true });

    expect(deriveWorktreePath(tmpDir, REPO, NAME)).toBe(expected(tmpDir));
  });

  it("prefers the new path when both layouts exist", async () => {
    await fsp.mkdir(path.join(tmpDir, NAME, REPO_NAME), { recursive: true });
    await fsp.mkdir(path.join(tmpDir, REPO_NAME, NAME), { recursive: true });

    expect(deriveWorktreePath(tmpDir, REPO, NAME)).toBe(
      path.join(tmpDir, NAME, REPO_NAME),
    );
  });

  it("derives the repo name from the folder path basename", () => {
    expect(deriveWorktreePath(tmpDir, "/a/b/other-repo", "feat")).toBe(
      path.join(tmpDir, "feat", "other-repo"),
    );
  });
});
