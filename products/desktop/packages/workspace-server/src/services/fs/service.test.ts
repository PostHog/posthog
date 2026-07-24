import { mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/git/queries", () => ({
  getChangedFiles: vi.fn(async () => new Set<string>()),
  listAllFiles: vi.fn(async () => []),
}));

import { getChangedFiles, listAllFiles } from "@posthog/git/queries";
import { FsService } from "./service";

describe("FsService.listRepoFiles", () => {
  it("derives directory entries alongside files", async () => {
    vi.mocked(getChangedFiles).mockResolvedValue(new Set());
    vi.mocked(listAllFiles).mockResolvedValue([
      "a.ts",
      "src/b.ts",
      "src/sub/c.ts",
    ]);

    const service = new FsService();
    const entries = await service.listRepoFiles("/repo");

    const dirs = entries
      .filter((e) => e.kind === "directory")
      .map((e) => e.path);
    const files = entries.filter((e) => e.kind === "file").map((e) => e.path);

    expect(dirs).toEqual(["src", "src/sub"]);
    expect(files).toEqual(["a.ts", "src/b.ts", "src/sub/c.ts"]);
  });

  it("filters directories and files by query substring", async () => {
    vi.mocked(getChangedFiles).mockResolvedValue(new Set());
    vi.mocked(listAllFiles).mockResolvedValue([
      "a.ts",
      "src/b.ts",
      "src/sub/c.ts",
    ]);

    const service = new FsService();
    const entries = await service.listRepoFiles("/repo", "sub");

    expect(entries.map((e) => ({ path: e.path, kind: e.kind }))).toEqual([
      { path: "src/sub", kind: "directory" },
      { path: "src/sub/c.ts", kind: "file" },
    ]);
  });

  it("passes the file cap and timeout through to listAllFiles", async () => {
    vi.mocked(getChangedFiles).mockResolvedValue(new Set());
    vi.mocked(listAllFiles).mockResolvedValue([]);

    const service = new FsService();
    await service.listRepoFiles("/repo");

    expect(listAllFiles).toHaveBeenCalledWith("/repo", {
      maxFiles: 50_000,
      timeoutMs: 8_000,
    });
  });

  it("total entries can exceed the file cap when derived directories are included", async () => {
    vi.mocked(getChangedFiles).mockResolvedValue(new Set());
    const cappedList = Array.from(
      { length: 50_000 },
      (_, i) => `src/sub${i}/file.ts`,
    );
    vi.mocked(listAllFiles).mockResolvedValue(cappedList);

    const service = new FsService();
    const entries = await service.listRepoFiles("/repo");

    const fileEntries = entries.filter((e) => e.kind === "file");
    expect(fileEntries.length).toBe(50_000);
    expect(entries.length).toBeGreaterThan(50_000);
  });
});

describe("FsService repo file IO", () => {
  let repo: string;
  const service = new FsService();

  beforeEach(async () => {
    repo = await mkdtemp(path.join(tmpdir(), "fs-service-test-"));
  });

  afterEach(async () => {
    await rm(repo, { recursive: true, force: true });
  });

  it("writes a repo file and reads it back", async () => {
    await service.writeRepoFile(repo, "file.txt", "hello");

    expect(await service.readRepoFile(repo, "file.txt")).toBe("hello");
    expect(await readFile(path.join(repo, "file.txt"), "utf-8")).toBe("hello");
  });

  it("returns null reading a missing file", async () => {
    expect(await service.readRepoFile(repo, "nope.txt")).toBeNull();
  });

  it("refuses to read outside the repository", async () => {
    await expect(
      service.readRepoFile(repo, "../escape.txt"),
    ).resolves.toBeNull();
    await expect(
      service.writeRepoFile(repo, "../escape.txt", "x"),
    ).rejects.toThrow(/Access denied/);
  });

  it("refuses to read through a symlink that escapes the repository", async () => {
    const outside = await mkdtemp(path.join(tmpdir(), "fs-service-outside-"));
    try {
      await writeFile(path.join(outside, "secret.txt"), "SECRET");
      // A symlink named like an ordinary repo file, pointing outside the repo:
      // the path is lexically inside the repo but resolves out of it.
      await symlink(
        path.join(outside, "secret.txt"),
        path.join(repo, "config.json"),
      );
      expect(await service.readRepoFile(repo, "config.json")).toBeNull();

      // Also blocked when reached through a symlinked directory.
      await symlink(outside, path.join(repo, "sub"));
      expect(await service.readRepoFile(repo, "sub/secret.txt")).toBeNull();
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });

  it("refuses to write through a symlink that escapes the repository", async () => {
    const outside = await mkdtemp(path.join(tmpdir(), "fs-service-outside-"));
    try {
      await writeFile(path.join(outside, "target.txt"), "original");
      await symlink(
        path.join(outside, "target.txt"),
        path.join(repo, "notes.txt"),
      );

      await expect(
        service.writeRepoFile(repo, "notes.txt", "attacker"),
      ).rejects.toThrow(/Access denied/);
      // The file outside the repo must be untouched.
      expect(await readFile(path.join(outside, "target.txt"), "utf-8")).toBe(
        "original",
      );
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });

  it("refuses to write through a dangling symlink that would create a file outside the repository", async () => {
    const outside = await mkdtemp(path.join(tmpdir(), "fs-service-outside-"));
    try {
      // A symlink whose target does NOT exist yet, pointing outside the repo.
      // fs.realpath throws ENOENT on such a link, so a containment check that
      // only realpaths the deepest existing component mistakes it for an in-repo
      // new file, so the write follows it and creates the outside file.
      const danglingTarget = path.join(outside, "brand-new.txt");
      await symlink(danglingTarget, path.join(repo, "evil.txt"));

      await expect(
        service.writeRepoFile(repo, "evil.txt", "attacker"),
      ).rejects.toThrow(/Access denied/);
      // The outside file must not have been created.
      await expect(readFile(danglingTarget, "utf-8")).rejects.toThrow();
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });

  it("confines readRepoFileAsBase64 to the repo (symlink escape blocked)", async () => {
    const outside = await mkdtemp(path.join(tmpdir(), "fs-service-outside-"));
    try {
      await writeFile(path.join(outside, "id_rsa"), "SSH-KEY");
      // A symlink committed under a binary filename, pointing outside the repo.
      await symlink(path.join(outside, "id_rsa"), path.join(repo, "logo.png"));

      // The escaping symlink is blocked.
      expect(await service.readRepoFileAsBase64(repo, "logo.png")).toBeNull();

      // A legitimate in-repo binary still reads.
      await writeFile(path.join(repo, "pic.png"), "PICBYTES");
      expect(await service.readRepoFileAsBase64(repo, "pic.png")).toBe(
        Buffer.from("PICBYTES").toString("base64"),
      );
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });

  it("bounds reads by line count", async () => {
    await service.writeRepoFile(repo, "small.txt", "a\nb\nc");
    await service.writeRepoFile(repo, "big.txt", "a\nb\nc\nd\ne");

    expect(await service.readRepoFileBounded(repo, "small.txt", 5)).toEqual({
      kind: "content",
      content: "a\nb\nc",
    });
    expect(await service.readRepoFileBounded(repo, "big.txt", 3)).toEqual({
      kind: "too-large",
    });
    expect(await service.readRepoFileBounded(repo, "missing.txt", 3)).toEqual({
      kind: "missing",
    });
  });
});
