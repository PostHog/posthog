#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { cp, mkdir, readdir, rm, stat } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPOSITORY_DIR = resolve(__dirname, "../../..");
const CHECKOUT_SKILLS_DIR = join(
  REPOSITORY_DIR,
  "products",
  "context_layer",
  "skills",
);
const LOCAL_SKILLS_DIR = join(
  __dirname,
  "..",
  "plugins",
  "posthog",
  "local-skills",
);

export async function syncCheckoutSkills({
  checkoutSkillsDir,
  localSkillsDir,
}) {
  const candidates = await readdir(checkoutSkillsDir, { withFileTypes: true });
  const entries = [];
  for (const entry of candidates) {
    if (
      entry.isDirectory() &&
      (
        await stat(join(checkoutSkillsDir, entry.name, "SKILL.md")).catch(
          () => null,
        )
      )?.isFile()
    ) {
      entries.push(entry.name);
    }
  }
  if (entries.length === 0) {
    throw new Error(`No checkout skills found at ${checkoutSkillsDir}`);
  }

  await mkdir(localSkillsDir, { recursive: true });
  const localEntries = await readdir(localSkillsDir);
  await Promise.all(
    localEntries
      .filter(
        (entry) =>
          entry.startsWith("context-layer-") || entries.includes(entry),
      )
      .map((entry) =>
        rm(join(localSkillsDir, entry), { recursive: true, force: true }),
      ),
  );
  await Promise.all(
    entries.map((entry) =>
      cp(join(checkoutSkillsDir, entry), join(localSkillsDir, entry), {
        recursive: true,
      }),
    ),
  );
}

async function main() {
  const args = process.argv.slice(2);
  if (args.some((arg) => arg !== "--all")) {
    throw new Error("Usage: pnpm skills:local [--all]");
  }

  let checkoutSkillsDir = CHECKOUT_SKILLS_DIR;
  if (args.includes("--all")) {
    console.log("Building all product skills from this checkout...");
    const result = spawnSync(
      "uv",
      ["run", "python", "products/posthog_ai/scripts/build_skills.py"],
      {
        cwd: REPOSITORY_DIR,
        stdio: "inherit",
        env: { ...process.env, DEBUG: process.env.DEBUG ?? "1" },
      },
    );
    if (result.error || result.status !== 0) {
      throw new Error(
        "Skill build failed. Check the build error above and the monorepo Python environment. Local skills were not changed.",
        { cause: result.error },
      );
    }
    checkoutSkillsDir = join(REPOSITORY_DIR, "products/posthog_ai/dist/skills");
  }

  await syncCheckoutSkills({
    checkoutSkillsDir,
    localSkillsDir: LOCAL_SKILLS_DIR,
  });
  console.log(
    `Local skills synced from ${checkoutSkillsDir} to ${LOCAL_SKILLS_DIR}`,
  );
}

if (fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  await main();
}
