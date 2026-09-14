#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  cp,
  mkdir,
  mkdtemp,
  readdir,
  rename,
  rm,
  stat,
} from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
export const REPOSITORY_DIR = resolve(__dirname, "../../..");

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

  await mkdir(dirname(localSkillsDir), { recursive: true });
  const stagingDir = await mkdtemp(`${localSkillsDir}.staging-`);
  try {
    await Promise.all(
      entries.map((entry) =>
        cp(join(checkoutSkillsDir, entry), join(stagingDir, entry), {
          recursive: true,
        }),
      ),
    );
    await rm(localSkillsDir, { recursive: true, force: true });
    await rename(stagingDir, localSkillsDir);
  } finally {
    await rm(stagingDir, { recursive: true, force: true });
  }
}

export async function skillSourceFingerprint(repositoryDir = REPOSITORY_DIR) {
  const productsDir = join(repositoryDir, "products");
  const products = await readdir(productsDir, { withFileTypes: true });
  const roots = products
    .filter((entry) => entry.isDirectory())
    .map((entry) => join(productsDir, entry.name, "skills"));
  roots.push(join(productsDir, "posthog_ai", "scripts"));
  const hash = createHash("sha256");
  for (const root of roots.sort()) {
    let entries;
    try {
      entries = await readdir(root, { recursive: true, withFileTypes: true });
    } catch (error) {
      if (error.code === "ENOENT") continue;
      throw error;
    }
    const paths = entries
      .filter(
        (entry) => entry.isFile() && !entry.parentPath.includes("__pycache__"),
      )
      .map((entry) => join(entry.parentPath, entry.name))
      .sort();
    for (const path of paths) {
      const metadata = await stat(path);
      hash.update(
        `${path}:${metadata.mtimeMs}:${metadata.ctimeMs}:${metadata.size}\n`,
      );
    }
  }
  return hash.digest("hex");
}
