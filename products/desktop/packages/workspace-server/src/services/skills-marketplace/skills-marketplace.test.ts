import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { strToU8, zipSync } from "fflate";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const testHome = vi.hoisted(() => ({ dir: "" }));

vi.mock("node:os", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:os")>();
  const homedir = () => testHome.dir;
  return { ...actual, homedir, default: { ...actual, homedir } };
});

import { existsSync } from "node:fs";
import {
  collectSkillFiles,
  findSkillDirPrefix,
  SkillsMarketplaceService,
  unzipWithLimit,
} from "./skills-marketplace";

function makeService(): SkillsMarketplaceService {
  return new SkillsMarketplaceService();
}

let root: string;

function makeRepoZip(extraEntries: Record<string, Uint8Array> = {}): Buffer {
  return Buffer.from(
    zipSync({
      "skills-HEAD/README.md": strToU8("# repo"),
      "skills-HEAD/skills/commit/SKILL.md": strToU8(
        "---\nname: commit\ndescription: Commits things\n---\nBody",
      ),
      "skills-HEAD/skills/commit/references/guide.md": strToU8("guide"),
      "skills-HEAD/skills/commit/scripts/run.sh": strToU8("echo hi"),
      "skills-HEAD/skills/other/SKILL.md": strToU8("---\nname: other\n---\n"),
      ...extraEntries,
    }),
  );
}

function stubFetch(handler: (url: string) => Response | Promise<Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL) => handler(String(input))),
  );
}

function zipResponse(zip: Buffer): Response {
  return new Response(new Uint8Array(zip), { status: 200 });
}

beforeEach(async () => {
  // /tmp directly: node:os is mocked, so os.tmpdir() is off the table here.
  root = await mkdtemp(path.join("/tmp", "skills-marketplace-test-"));
  testHome.dir = root;
});

afterEach(async () => {
  vi.unstubAllGlobals();
  await rm(root, { recursive: true, force: true });
});

describe("findSkillDirPrefix", () => {
  it("finds the shallowest directory with the skill id", () => {
    const entries = {
      "repo-HEAD/nested/deep/commit/SKILL.md": strToU8("x"),
      "repo-HEAD/skills/commit/SKILL.md": strToU8("x"),
    };

    expect(findSkillDirPrefix(entries, "commit")).toBe(
      "repo-HEAD/skills/commit/",
    );
  });

  it("returns null when absent", () => {
    expect(findSkillDirPrefix({}, "commit")).toBeNull();
  });
});

describe("collectSkillFiles", () => {
  it("drops entries that would escape the install directory", () => {
    const prefix = "repo-HEAD/skills/commit/";
    const entries = {
      [`${prefix}SKILL.md`]: strToU8("ok"),
      [`${prefix}../evil.md`]: strToU8("bad"),
      [`${prefix}nested/../../evil2.md`]: strToU8("bad"),
      [`${prefix}back\\slash.md`]: strToU8("bad"),
    };

    const files = collectSkillFiles(entries, prefix);

    expect([...files.keys()]).toEqual(["SKILL.md"]);
  });
});

describe("search", () => {
  it("maps skills.sh results and marks installed skills", async () => {
    const service = makeService();
    // Install state: "commit" is already installed.
    const stateDir = path.join(root, ".claude", "skills");
    await import("node:fs/promises").then((fsp) =>
      fsp.mkdir(stateDir, { recursive: true }),
    );
    await writeFile(
      path.join(stateDir, "installed.json"),
      JSON.stringify({
        version: 1,
        installed: { commit: { repo: "getsentry/skills" } },
      }),
    );

    stubFetch((url) => {
      expect(url).toContain("skills.sh/api/search");
      expect(url).toContain("q=commit");
      return new Response(
        JSON.stringify({
          skills: [
            {
              id: "getsentry/skills/commit",
              skillId: "commit",
              name: "commit",
              installs: 2693,
              source: "getsentry/skills",
            },
            {
              id: "acme/tools/review",
              skillId: "review",
              name: "review",
              source: "acme/tools",
            },
          ],
        }),
        { status: 200 },
      );
    });

    const { results } = await service.search("commit");

    expect(results).toEqual([
      expect.objectContaining({ skillId: "commit", installed: true }),
      expect.objectContaining({
        skillId: "review",
        installs: 0,
        installed: false,
      }),
    ]);
  });

  it("returns empty results for queries under two characters", async () => {
    stubFetch(() => {
      throw new Error("should not fetch");
    });

    expect(await makeService().search(" a ")).toEqual({
      results: [],
    });
  });
});

describe("preview", () => {
  it("returns the full file list with contents and a scripts flag", async () => {
    stubFetch(() => zipResponse(makeRepoZip()));
    const service = makeService();

    const preview = await service.preview({
      source: "getsentry/skills",
      skillId: "commit",
    });

    expect(preview.files.map((f) => f.path)).toEqual([
      "SKILL.md",
      "references/guide.md",
      "scripts/run.sh",
    ]);
    expect(preview.files[0]?.content).toContain("Commits things");
    expect(preview.hasScripts).toBe(true);
  });

  it("marks binary files as non-previewable", async () => {
    stubFetch(() =>
      zipResponse(
        makeRepoZip({
          "skills-HEAD/skills/commit/assets/logo.png": new Uint8Array([
            0x89, 0x50, 0x00, 0x47,
          ]),
        }),
      ),
    );

    const preview = await makeService().preview({
      source: "getsentry/skills",
      skillId: "commit",
    });

    const logo = preview.files.find((f) => f.path === "assets/logo.png");
    expect(logo?.content).toBeNull();
  });

  it("throws when the skill is not in the repository", async () => {
    stubFetch(() => zipResponse(makeRepoZip()));

    await expect(
      makeService().preview({
        source: "getsentry/skills",
        skillId: "nope",
      }),
    ).rejects.toThrow('Skill "nope" was not found');
  });

  it("rejects malformed repository references", async () => {
    stubFetch(() => zipResponse(makeRepoZip()));

    await expect(
      makeService().preview({
        source: "https://evil.example/x",
        skillId: "commit",
      }),
    ).rejects.toThrow("Invalid repository reference");
  });
});

describe("install", () => {
  it("copies the skill into the user skills dir and records the badge state", async () => {
    stubFetch(() => zipResponse(makeRepoZip()));
    const service = makeService();

    const { path: installedPath } = await service.install({
      source: "getsentry/skills",
      skillId: "commit",
    });

    expect(installedPath).toBe(path.join(root, ".claude", "skills", "commit"));
    expect(
      await readFile(path.join(installedPath, "SKILL.md"), "utf-8"),
    ).toContain("Commits things");
    expect(existsSync(path.join(installedPath, "scripts", "run.sh"))).toBe(
      true,
    );

    const state = JSON.parse(
      await readFile(
        path.join(root, ".claude", "skills", "installed.json"),
        "utf-8",
      ),
    );
    expect(state).toEqual({
      version: 1,
      installed: { commit: { repo: "getsentry/skills" } },
    });
  });

  it("requires overwrite when the skill already exists, then replaces it", async () => {
    stubFetch(() => zipResponse(makeRepoZip()));
    const service = makeService();

    const { path: installedPath } = await service.install({
      source: "getsentry/skills",
      skillId: "commit",
    });
    await writeFile(path.join(installedPath, "local-edit.md"), "mine");

    await expect(
      service.install({ source: "getsentry/skills", skillId: "commit" }),
    ).rejects.toThrow("already exists");

    await service.install(
      { source: "getsentry/skills", skillId: "commit" },
      true,
    );
    // Overwrite replaces the directory wholesale; local edits are gone.
    expect(existsSync(path.join(installedPath, "local-edit.md"))).toBe(false);
    expect(existsSync(path.join(installedPath, "SKILL.md"))).toBe(true);
  });

  it("rejects invalid skill ids", async () => {
    stubFetch(() => zipResponse(makeRepoZip()));

    await expect(
      makeService().install({
        source: "getsentry/skills",
        skillId: "../escape",
      }),
    ).rejects.toThrow("Skill names must be");
  });
});

describe("archive download guards", () => {
  it("rejects archives whose declared content-length exceeds the cap", async () => {
    stubFetch(
      () =>
        new Response(new Uint8Array(makeRepoZip()), {
          status: 200,
          headers: { "content-length": String(101 * 1024 * 1024) },
        }),
    );

    await expect(
      makeService().preview({
        source: "getsentry/skills",
        skillId: "commit",
      }),
    ).rejects.toThrow("too large to download");
  });

  it("reuses the cached archive within the TTL", async () => {
    stubFetch(() => zipResponse(makeRepoZip()));
    const service = makeService();

    await service.preview({ source: "getsentry/skills", skillId: "commit" });
    await service.preview({ source: "getsentry/skills", skillId: "other" });

    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  });
});

describe("unzipWithLimit", () => {
  it("rejects archives that decompress past the budget", async () => {
    const zip = zipSync({
      "repo-HEAD/big.bin": new Uint8Array(64 * 1024),
    });

    await expect(
      unzipWithLimit(new Uint8Array(zip), 16 * 1024, "a/b"),
    ).rejects.toThrow("too large to unpack");
  });

  it("inflates archives within the budget", async () => {
    const zip = zipSync({ "repo-HEAD/small.txt": strToU8("hello") });

    const entries = await unzipWithLimit(new Uint8Array(zip), 16 * 1024, "a/b");

    expect(Object.keys(entries)).toContain("repo-HEAD/small.txt");
  });
});
