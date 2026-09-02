import { vol } from "memfs";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("node:fs/promises", async () => {
  const { fs } = await import("memfs");
  return { ...fs.promises, default: fs.promises };
});

const listWorktrees = vi.fn();
vi.mock("@posthog/git/queries", () => ({
  listWorktrees: (...args: unknown[]) => listWorktrees(...args),
}));

import {
  getWorktreeFileUsage,
  listLinkedWorktrees,
  listTwigWorktrees,
} from "./worktree-query";

afterEach(() => {
  vol.reset();
  listWorktrees.mockReset();
});

const MAIN = "/repos/app";
const BASE = "/repos/app/.worktrees";

describe("listTwigWorktrees", () => {
  it("excludes the main repo from the results", async () => {
    listWorktrees.mockResolvedValue([
      { path: MAIN, head: "h0", branch: "main" },
      { path: `${BASE}/feat`, head: "h1", branch: "feat" },
    ]);

    const result = await listTwigWorktrees(MAIN, BASE);

    expect(result).toEqual([
      { worktreePath: `${BASE}/feat`, head: "h1", branch: "feat" },
    ]);
  });

  it("excludes worktrees that live outside the twig base path", async () => {
    listWorktrees.mockResolvedValue([
      { path: `${BASE}/feat`, head: "h1", branch: "feat" },
      { path: "/elsewhere/rogue", head: "h2", branch: "rogue" },
    ]);

    const result = await listTwigWorktrees(MAIN, BASE);

    expect(result.map((w) => w.worktreePath)).toEqual([`${BASE}/feat`]);
  });

  it("preserves a detached worktree's null branch", async () => {
    listWorktrees.mockResolvedValue([
      { path: `${BASE}/detached`, head: "h3", branch: null },
    ]);

    const [worktree] = await listTwigWorktrees(MAIN, BASE);

    expect(worktree.branch).toBeNull();
  });

  it("returns an empty list when only the main repo exists", async () => {
    listWorktrees.mockResolvedValue([
      { path: MAIN, head: "h0", branch: "main" },
    ]);

    expect(await listTwigWorktrees(MAIN, BASE)).toEqual([]);
  });
});

describe("listLinkedWorktrees", () => {
  it("excludes the main repo but keeps worktrees in any location", async () => {
    listWorktrees.mockResolvedValue([
      { path: MAIN, head: "h0", branch: "main" },
      { path: `${BASE}/feat`, head: "h1", branch: "feat" },
      { path: "/elsewhere/rogue", head: "h2", branch: "rogue" },
    ]);

    const result = await listLinkedWorktrees(MAIN);

    expect(result).toEqual([
      { worktreePath: `${BASE}/feat`, head: "h1", branch: "feat" },
      { worktreePath: "/elsewhere/rogue", head: "h2", branch: "rogue" },
    ]);
  });

  it("returns an empty list when only the main repo exists", async () => {
    listWorktrees.mockResolvedValue([
      { path: MAIN, head: "h0", branch: "main" },
    ]);

    expect(await listLinkedWorktrees(MAIN)).toEqual([]);
  });
});

describe("getWorktreeFileUsage", () => {
  it("reports usage when an exclude file has a real entry", async () => {
    vol.fromJSON({ [`${MAIN}/.worktreelink`]: "node_modules\n" }, "/");

    const result = await getWorktreeFileUsage(MAIN);

    expect(result).toEqual({
      usesWorktreeLink: true,
      usesWorktreeInclude: false,
    });
  });

  it("ignores blank lines and comments when detecting entries", async () => {
    vol.fromJSON(
      { [`${MAIN}/.worktreeinclude`]: "# just a comment\n\n   \n" },
      "/",
    );

    const result = await getWorktreeFileUsage(MAIN);

    expect(result.usesWorktreeInclude).toBe(false);
  });

  it("counts a commented file with one live entry as used", async () => {
    vol.fromJSON({ [`${MAIN}/.worktreeinclude`]: "# header\ndist\n" }, "/");

    const result = await getWorktreeFileUsage(MAIN);

    expect(result.usesWorktreeInclude).toBe(true);
  });

  it("reports no usage when neither exclude file exists", async () => {
    vol.fromJSON({ [`${MAIN}/README.md`]: "hi" }, "/");

    const result = await getWorktreeFileUsage(MAIN);

    expect(result).toEqual({
      usesWorktreeLink: false,
      usesWorktreeInclude: false,
    });
  });
});
