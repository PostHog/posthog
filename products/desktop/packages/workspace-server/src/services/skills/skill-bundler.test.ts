import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { unzipSync } from "fflate";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { bundleLocalSkill, countFilesByTopLevelDir } from "./skill-bundler";

let root: string;

beforeEach(async () => {
  root = await mkdtemp(path.join(tmpdir(), "skill-bundler-test-"));
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

describe("bundleLocalSkill", () => {
  it("bundles dot-files but not ignored directories", async () => {
    const skillPath = path.join(root, "my-skill");
    await mkdir(path.join(skillPath, "references"), { recursive: true });
    await mkdir(path.join(skillPath, ".venv", "lib"), { recursive: true });
    await writeFile(path.join(skillPath, "SKILL.md"), "# my-skill");
    await writeFile(path.join(skillPath, ".gitignore"), "junk");
    await writeFile(path.join(skillPath, "..lock.md"), "dots");
    await writeFile(path.join(skillPath, "references", "x.md"), "x");
    await writeFile(path.join(skillPath, ".venv", "lib", "mod.py"), "m");

    const bundle = await bundleLocalSkill({
      name: "my-skill",
      source: "user",
      skillPath,
    });

    const zipped = unzipSync(
      new Uint8Array(Buffer.from(bundle.contentBase64, "base64")),
    );
    expect(Object.keys(zipped).sort()).toEqual([
      "..lock.md",
      ".gitignore",
      "SKILL.md",
      "posthog-skill-bundle.json",
      "references/x.md",
    ]);
  });

  it("names the largest folders with full counts when the file cap is exceeded", async () => {
    const skillPath = path.join(root, "big-skill");
    await mkdir(path.join(skillPath, "aaa"), { recursive: true });
    await mkdir(path.join(skillPath, "zzz"), { recursive: true });
    await writeFile(path.join(skillPath, "SKILL.md"), "# big-skill");
    await Promise.all(
      Array.from({ length: 600 }, (_, i) =>
        writeFile(path.join(skillPath, "aaa", `f${i}.txt`), "x"),
      ),
    );
    await Promise.all(
      Array.from({ length: 600 }, (_, i) =>
        writeFile(path.join(skillPath, "zzz", `f${i}.txt`), "x"),
      ),
    );

    // The collection walk stops at the cap, so only a full recount can
    // attribute 600 files to whichever folder was walked second.
    const failure = bundleLocalSkill({
      name: "big-skill",
      source: "user",
      skillPath,
    });
    await expect(failure).rejects.toThrow(/more than 1000 files\./);
    await expect(failure).rejects.toThrow(/aaa \(600 files\)/);
    await expect(failure).rejects.toThrow(/zzz \(600 files\)/);
  });
});

describe("countFilesByTopLevelDir", () => {
  it("stops once the entry budget is spent instead of walking the whole tree", async () => {
    const skillPath = path.join(root, "huge-skill");
    await mkdir(path.join(skillPath, "aaa"), { recursive: true });
    await Promise.all(
      Array.from({ length: 20 }, (_, i) =>
        writeFile(path.join(skillPath, "aaa", `f${i}.txt`), "x"),
      ),
    );

    const counts = await countFilesByTopLevelDir(skillPath, 5);

    const totalCounted = [...counts.values()].reduce((a, b) => a + b, 0);
    expect(totalCounted).toBeLessThan(20);
  });
});
