#!/usr/bin/env node

/**
 * Downloads remote skills into local-skills/ for local editing/testing.
 *
 * Usage: pnpm pull-skills
 *
 * The downloaded skills land in plugins/posthog/local-skills/ which is
 * gitignored and overlaid on top of shipped + remote skills by the Vite dev build.
 */

import { execFile } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { cp, mkdir, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { unzipSync } from "fflate";

const execFileAsync = promisify(execFile);
const __dirname = dirname(fileURLToPath(import.meta.url));
const SKILLS_ZIP_URL =
  "https://github.com/PostHog/posthog/releases/download/agent-skills-latest/skills.zip";
const CONTEXT_MILL_ZIP_URL =
  "https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip";
const LOCAL_SKILLS_DIR = join(
  __dirname,
  "..",
  "plugins",
  "posthog",
  "local-skills",
);

function getDesktopContextMillSkillFiles(entries) {
  const manifestData = entries["manifest.json"];
  if (!manifestData) return new Set();

  try {
    const manifest = JSON.parse(new TextDecoder().decode(manifestData));
    return new Set(
      (manifest.resources ?? [])
        .filter((resource) => resource.desktop && resource.file)
        .map((resource) => resource.file),
    );
  } catch {
    return new Set();
  }
}

const tempDir = join(tmpdir(), `posthog-code-pull-skills-${Date.now()}`);
await mkdir(tempDir, { recursive: true });

try {
  const zipPath = join(tempDir, "skills.zip");

  console.log("Downloading skills.zip...");
  await execFileAsync("curl", ["-fsSL", "-o", zipPath, SKILLS_ZIP_URL], {
    timeout: 30_000,
  });

  const extractDir = join(tempDir, "extracted");
  await mkdir(extractDir, { recursive: true });
  const zipData = readFileSync(zipPath);
  const unzipped = unzipSync(new Uint8Array(zipData));
  for (const [filename, content] of Object.entries(unzipped)) {
    const fullPath = join(extractDir, filename);
    if (filename.endsWith("/")) {
      await mkdir(fullPath, { recursive: true });
    } else {
      await mkdir(dirname(fullPath), { recursive: true });
      await writeFile(fullPath, content);
    }
  }

  // Find the skills directory
  let skillsSource = null;
  const direct = join(extractDir, "skills");
  if (existsSync(direct)) {
    skillsSource = direct;
  } else {
    // Check one level deep
    const entries = await readdir(extractDir, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isDirectory()) {
        const nested = join(extractDir, entry.name, "skills");
        if (existsSync(nested)) {
          skillsSource = nested;
          break;
        }
      }
    }
  }

  if (!skillsSource) {
    // The extracted dir itself might contain skill directories
    const entries = await readdir(extractDir, { withFileTypes: true });
    const hasSkillDirs = entries.some(
      (e) =>
        e.isDirectory() && existsSync(join(extractDir, e.name, "SKILL.md")),
    );
    if (hasSkillDirs) {
      skillsSource = extractDir;
    }
  }

  if (!skillsSource) {
    console.error("No skills directory found in downloaded archive");
    process.exit(1);
  }

  // Copy to local-skills/
  await rm(LOCAL_SKILLS_DIR, { recursive: true, force: true });
  await cp(skillsSource, LOCAL_SKILLS_DIR, { recursive: true });

  // Download and merge selected context-mill skills (non-fatal)
  try {
    const cmZipPath = join(tempDir, "context-mill.zip");
    console.log("Downloading context-mill skills-mcp-resources.zip...");
    await execFileAsync(
      "curl",
      ["-fsSL", "-o", cmZipPath, CONTEXT_MILL_ZIP_URL],
      { timeout: 30_000 },
    );

    const cmZipData = readFileSync(cmZipPath);
    const cmOuter = unzipSync(new Uint8Array(cmZipData));
    const desktopSkillFiles = getDesktopContextMillSkillFiles(cmOuter);

    for (const [filename, content] of Object.entries(cmOuter)) {
      const base = filename.replace(/^.*\//, "");
      if (!base.endsWith(".zip")) continue;

      const archiveName = base.replace(/\.zip$/, "");
      if (!desktopSkillFiles.has(base) && !archiveName.startsWith("omnibus-")) {
        continue;
      }

      const strippedName = archiveName.replace(/^omnibus-/, "");
      const innerEntries = unzipSync(new Uint8Array(content));
      const destDir = join(LOCAL_SKILLS_DIR, strippedName);
      await mkdir(destDir, { recursive: true });

      for (const [innerFile, innerContent] of Object.entries(innerEntries)) {
        if (innerFile.endsWith("/")) {
          await mkdir(join(destDir, innerFile), { recursive: true });
        } else {
          await mkdir(dirname(join(destDir, innerFile)), { recursive: true });
          if (innerFile === "SKILL.md" || innerFile.endsWith("/SKILL.md")) {
            const text = new TextDecoder().decode(innerContent);
            const patched = text.replace(/^(name:\s*)omnibus-/m, "$1");
            await writeFile(join(destDir, innerFile), patched);
          } else {
            await writeFile(join(destDir, innerFile), innerContent);
          }
        }
      }
    }
    console.log("Selected context-mill skills merged into local-skills/");
  } catch (err) {
    console.warn(
      "Failed to download context-mill skills (non-fatal):",
      err.message,
    );
  }

  console.log(`Skills extracted to ${LOCAL_SKILLS_DIR}`);
  console.log("Edit skills locally — Vite will hot-reload them in dev mode.");
} finally {
  await rm(tempDir, { recursive: true, force: true });
}
