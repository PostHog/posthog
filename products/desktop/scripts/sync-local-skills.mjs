#!/usr/bin/env node

import { cp, mkdir, readdir, rm } from "node:fs/promises";
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
  const entries = await readdir(checkoutSkillsDir);
  if (entries.length === 0) {
    throw new Error(`No checkout skills found at ${checkoutSkillsDir}`);
  }

  await mkdir(localSkillsDir, { recursive: true });
  const localEntries = await readdir(localSkillsDir);
  await Promise.all(
    localEntries
      .filter((entry) => entry.startsWith("context-layer-"))
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
  await syncCheckoutSkills({
    checkoutSkillsDir: CHECKOUT_SKILLS_DIR,
    localSkillsDir: LOCAL_SKILLS_DIR,
  });
  console.log(
    `Context layer skills synced from this checkout to ${LOCAL_SKILLS_DIR}`,
  );
}

if (fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  await main();
}
