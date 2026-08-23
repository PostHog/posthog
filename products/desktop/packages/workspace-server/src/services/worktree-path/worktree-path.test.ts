import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  deriveWorktreePath,
  removeManagedWorktreeWrapper,
} from "./worktree-path";

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

describe("removeManagedWorktreeWrapper", () => {
  let tmpDir: string;
  let externalRoot: string;

  beforeEach(async () => {
    tmpDir = await fsp.mkdtemp(path.join(os.tmpdir(), "wt-wrapper-"));
    externalRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "wt-external-"));
  });

  afterEach(async () => {
    await fsp.rm(tmpDir, { recursive: true, force: true });
    await fsp.rm(externalRoot, { recursive: true, force: true });
  });

  it.each([
    {
      label: "new layout wrapper <base>/<name>",
      layout: (base: string) => path.join(base, NAME, "repo"),
    },
    {
      label: "legacy layout wrapper <base>/<repo>",
      layout: (base: string) => path.join(base, "repo", NAME),
    },
  ])(
    "removes the empty $label after the worktree is gone",
    async ({ layout }) => {
      const worktreePath = layout(tmpDir);
      await fsp.mkdir(path.dirname(worktreePath), { recursive: true });

      const removed = await removeManagedWorktreeWrapper(worktreePath, tmpDir);

      expect(removed).toBe(true);
      await expect(fsp.access(path.dirname(worktreePath))).rejects.toThrow();
      await expect(fsp.access(tmpDir)).resolves.toBeUndefined();
    },
  );

  it.each([
    {
      label: "an adopted checkout outside the base",
      worktreePath: () =>
        path.join(externalRoot, "code-parent", "repo.feature"),
      sentinel: () => path.join(externalRoot, "code-parent", "main-repo"),
    },
    {
      label: "a nested path two levels under the base",
      worktreePath: () => path.join(tmpDir, "nested", "deeper", "repo"),
      sentinel: () => path.join(tmpDir, "nested", "keep-me.txt"),
    },
    {
      label: "the base directory itself",
      worktreePath: () => path.join(tmpDir, "repo"),
      sentinel: () => path.join(tmpDir, "keep-me"),
    },
  ])(
    "refuses to touch the parent of $label",
    async ({ worktreePath, sentinel }) => {
      const wt = worktreePath();
      const guard = sentinel();
      await fsp.mkdir(path.dirname(wt), { recursive: true });
      await fsp.writeFile(guard, "survivor");

      const removed = await removeManagedWorktreeWrapper(wt, tmpDir);

      expect(removed).toBe(false);
      await expect(fsp.access(path.dirname(wt))).resolves.toBeUndefined();
      await expect(fsp.access(guard)).resolves.toBeUndefined();
    },
  );

  it("keeps a non-empty legacy wrapper holding sibling worktrees", async () => {
    const wrapper = path.join(tmpDir, "repo");
    await fsp.mkdir(path.join(wrapper, NAME), { recursive: true });
    await fsp.mkdir(path.join(wrapper, "sibling-wt"), { recursive: true });

    const removed = await removeManagedWorktreeWrapper(
      path.join(wrapper, NAME),
      tmpDir,
    );

    expect(removed).toBe(false);
    await expect(
      fsp.access(path.join(wrapper, "sibling-wt")),
    ).resolves.toBeUndefined();
  });

  it("returns false without throwing for paths that do not exist", async () => {
    const removed = await removeManagedWorktreeWrapper(
      path.join(tmpDir, "missing-name", "repo"),
      tmpDir,
    );

    expect(removed).toBe(false);
  });
});
