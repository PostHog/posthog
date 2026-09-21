import assert from "node:assert/strict";
import {
  mkdir,
  mkdtemp,
  readFile,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, test } from "node:test";

import {
  skillSourceFingerprint,
  syncCheckoutSkills,
} from "./sync-local-skills.mjs";

const temporaryDirectories = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

test("replaces managed skills and removes deleted files without changing manual overrides", async () => {
  const root = await mkdtemp(join(tmpdir(), "posthog-local-skills-"));
  temporaryDirectories.push(root);
  const checkoutSkillsDir = join(root, "checkout");
  const localSkillsDir = join(root, "local");
  const manualSkillsDir = join(root, "manual");
  await mkdir(join(checkoutSkillsDir, "context-layer-dreaming"), {
    recursive: true,
  });
  await mkdir(join(localSkillsDir, "context-layer-dreaming"), {
    recursive: true,
  });
  await mkdir(join(manualSkillsDir, "manual-only"), { recursive: true });
  await mkdir(join(localSkillsDir, "deleted-skill"), { recursive: true });
  await mkdir(join(checkoutSkillsDir, "query-data"), { recursive: true });
  await mkdir(join(localSkillsDir, "query-data", "references"), {
    recursive: true,
  });
  await writeFile(
    join(checkoutSkillsDir, "query-data", "SKILL.md"),
    "rendered",
  );
  await writeFile(join(checkoutSkillsDir, ".build-hash"), "build metadata");
  await writeFile(join(localSkillsDir, "query-data", "SKILL.md"), "old");
  await writeFile(
    join(localSkillsDir, "query-data", "references", "removed.md"),
    "outdated reference",
  );
  await writeFile(
    join(checkoutSkillsDir, "context-layer-dreaming", "SKILL.md"),
    "checkout version",
  );
  await writeFile(
    join(localSkillsDir, "context-layer-dreaming", "SKILL.md"),
    "production version",
  );
  await writeFile(join(manualSkillsDir, "manual-only", "SKILL.md"), "keep");
  await writeFile(join(localSkillsDir, "deleted-skill", "SKILL.md"), "remove");

  await syncCheckoutSkills({ checkoutSkillsDir, localSkillsDir });

  assert.equal(
    await readFile(
      join(localSkillsDir, "context-layer-dreaming", "SKILL.md"),
      "utf8",
    ),
    "checkout version",
  );
  assert.equal(
    await readFile(join(manualSkillsDir, "manual-only", "SKILL.md"), "utf8"),
    "keep",
  );
  assert.equal(
    await readFile(join(localSkillsDir, "query-data", "SKILL.md"), "utf8"),
    "rendered",
  );
  await assert.rejects(
    readFile(join(localSkillsDir, "query-data", "references", "removed.md")),
    { code: "ENOENT" },
  );
  await assert.rejects(readFile(join(localSkillsDir, ".build-hash")), {
    code: "ENOENT",
  });
  await assert.rejects(
    readFile(join(localSkillsDir, "deleted-skill", "SKILL.md")),
    {
      code: "ENOENT",
    },
  );
  await rm(checkoutSkillsDir, { recursive: true });
  await mkdir(checkoutSkillsDir);
  await assert.rejects(
    syncCheckoutSkills({ checkoutSkillsDir, localSkillsDir }),
    /No checkout skills/,
  );
  assert.equal(
    await readFile(join(localSkillsDir, "query-data", "SKILL.md"), "utf8"),
    "rendered",
  );
});

test("detects skill edits, additions, renames, removals and renderer changes but ignores output", async () => {
  const root = await mkdtemp(join(tmpdir(), "posthog-skill-watch-"));
  temporaryDirectories.push(root);
  await mkdir(join(root, "products"));
  const skillDir = join(root, "products", "example", "skills", "example");
  const rendererDir = join(root, "products", "posthog_ai", "scripts");
  const outputDir = join(root, "products", "posthog_ai", "dist", "skills");
  let fingerprint = await skillSourceFingerprint(root);
  const changes = [
    async () => {
      await mkdir(skillDir, { recursive: true });
      await writeFile(join(skillDir, "SKILL.md"), "first");
    },
    () => writeFile(join(skillDir, "SKILL.md"), "updated instructions"),
    () => rename(join(skillDir, "SKILL.md"), join(skillDir, "SKILL.md.j2")),
    () => rm(join(skillDir, "SKILL.md.j2")),
    async () => {
      await mkdir(rendererDir, { recursive: true });
      await writeFile(join(rendererDir, "build_skills.py"), "renderer");
    },
  ];
  for (const change of changes) {
    await change();
    const next = await skillSourceFingerprint(root);
    assert.notEqual(next, fingerprint);
    fingerprint = next;
  }
  await mkdir(outputDir, { recursive: true });
  await writeFile(join(outputDir, "SKILL.md"), "generated");
  assert.equal(await skillSourceFingerprint(root), fingerprint);
});
