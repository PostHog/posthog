import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, test } from "node:test";

import { syncCheckoutSkills } from "./sync-local-skills.mjs";

const temporaryDirectories = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

test("overrides context layer skills without removing other local skills", async () => {
  const root = await mkdtemp(join(tmpdir(), "posthog-local-skills-"));
  temporaryDirectories.push(root);
  const checkoutSkillsDir = join(root, "checkout");
  const localSkillsDir = join(root, "local");
  await mkdir(join(checkoutSkillsDir, "context-layer-dreaming"), {
    recursive: true,
  });
  await mkdir(join(localSkillsDir, "context-layer-dreaming"), {
    recursive: true,
  });
  await mkdir(join(localSkillsDir, "production-only"), { recursive: true });
  await writeFile(
    join(checkoutSkillsDir, "context-layer-dreaming", "SKILL.md"),
    "checkout version",
  );
  await writeFile(
    join(localSkillsDir, "context-layer-dreaming", "SKILL.md"),
    "production version",
  );
  await writeFile(join(localSkillsDir, "production-only", "SKILL.md"), "keep");

  await syncCheckoutSkills({ checkoutSkillsDir, localSkillsDir });

  assert.equal(
    await readFile(
      join(localSkillsDir, "context-layer-dreaming", "SKILL.md"),
      "utf8",
    ),
    "checkout version",
  );
  assert.equal(
    await readFile(join(localSkillsDir, "production-only", "SKILL.md"), "utf8"),
    "keep",
  );
});
