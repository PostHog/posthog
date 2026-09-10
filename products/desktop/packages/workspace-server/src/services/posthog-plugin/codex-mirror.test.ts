import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanupLegacyCodexMirror, readCodexMirrorState } from "./codex-mirror";

let root: string;
let bundledDir: string;
let codexDir: string;

async function createSkill(dir: string, name: string, body = `# ${name}`) {
  await mkdir(path.join(dir, name), { recursive: true });
  await writeFile(path.join(dir, name, "SKILL.md"), body);
}

beforeEach(async () => {
  root = await mkdtemp(path.join(tmpdir(), "codex-mirror-test-"));
  bundledDir = path.join(root, "bundled-skills");
  codexDir = path.join(root, "codex-skills");
  await mkdir(bundledDir, { recursive: true });
});

afterEach(async () => {
  await rm(root, { recursive: true, force: true });
});

describe("cleanupLegacyCodexMirror", () => {
  it("removes tracked mirror copies and deletes the state file", async () => {
    await createSkill(codexDir, "alpha", "mirrored copy");
    await createSkill(codexDir, "beta", "mirrored copy");
    await writeFile(
      path.join(codexDir, ".posthog-mirror.json"),
      JSON.stringify({ version: 1, mirrored: ["alpha", "beta"] }),
    );

    const removed = await cleanupLegacyCodexMirror(codexDir, bundledDir);

    expect(removed.sort()).toEqual(["alpha", "beta"]);
    expect(existsSync(path.join(codexDir, "alpha"))).toBe(false);
    expect(existsSync(path.join(codexDir, "beta"))).toBe(false);
    expect(existsSync(path.join(codexDir, ".posthog-mirror.json"))).toBe(false);
  });

  it("removes bundled-catalog copies with identical SKILL.md", async () => {
    await createSkill(bundledDir, "query-data", "bundled body");
    await createSkill(codexDir, "query-data", "bundled body");

    const removed = await cleanupLegacyCodexMirror(codexDir, bundledDir);

    expect(removed).toEqual(["query-data"]);
    expect(existsSync(path.join(codexDir, "query-data"))).toBe(false);
  });

  it("keeps a user's own skill that shares a bundled name but differs", async () => {
    await createSkill(bundledDir, "query-data", "bundled body");
    await createSkill(codexDir, "query-data", "the user's own different body");

    const removed = await cleanupLegacyCodexMirror(codexDir, bundledDir);

    expect(removed).toEqual([]);
    expect(existsSync(path.join(codexDir, "query-data"))).toBe(true);
  });

  it("keeps untracked, non-bundled codex skills", async () => {
    await createSkill(codexDir, "my-codex-skill", "wholly the user's");

    const removed = await cleanupLegacyCodexMirror(codexDir, bundledDir);

    expect(removed).toEqual([]);
    expect(existsSync(path.join(codexDir, "my-codex-skill"))).toBe(true);
  });

  it("returns nothing when the codex dir does not exist", async () => {
    const removed = await cleanupLegacyCodexMirror(
      path.join(root, "missing"),
      bundledDir,
    );
    expect(removed).toEqual([]);
  });

  it("never deletes the codex dir or its parent from unsafe mirror names", async () => {
    await createSkill(codexDir, "keep-me", "the user's own");
    await writeFile(
      path.join(codexDir, ".posthog-mirror.json"),
      JSON.stringify({
        version: 1,
        mirrored: ["", ".", "..", "../../escape", "nested/evil"],
      }),
    );

    const removed = await cleanupLegacyCodexMirror(codexDir, bundledDir);

    expect(removed).toEqual([]);
    expect(existsSync(root)).toBe(true);
    expect(existsSync(codexDir)).toBe(true);
    expect(existsSync(path.join(codexDir, "keep-me"))).toBe(true);
  });
});

describe("readCodexMirrorState", () => {
  it("returns an empty state for a missing or corrupt file", async () => {
    expect(await readCodexMirrorState(codexDir)).toEqual({
      version: 1,
      mirrored: [],
    });

    await mkdir(codexDir, { recursive: true });
    await writeFile(path.join(codexDir, ".posthog-mirror.json"), "not json");
    expect(await readCodexMirrorState(codexDir)).toEqual({
      version: 1,
      mirrored: [],
    });
  });

  it("drops unsafe entries that could escape the codex dir", async () => {
    await mkdir(codexDir, { recursive: true });
    await writeFile(
      path.join(codexDir, ".posthog-mirror.json"),
      JSON.stringify({
        version: 1,
        mirrored: ["good", "", ".", "..", "nested/evil", "back\\slash", 42],
      }),
    );
    expect(await readCodexMirrorState(codexDir)).toEqual({
      version: 1,
      mirrored: ["good"],
    });
  });
});
