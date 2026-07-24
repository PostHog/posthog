import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { strToU8, zipSync } from "fflate";
import type { BundleLocalSkillOutput, UploadableSkillSource } from "./schemas";

const SKILL_BUNDLE_MAX_BYTES = 30 * 1024 * 1024;
const SKILL_BUNDLE_MAX_FILES = 1000;
const IGNORED_ENTRIES = new Set([
  ".DS_Store",
  ".git",
  "node_modules",
  "__pycache__",
]);

function toZipPath(filePath: string): string {
  return filePath.split(path.sep).join("/");
}

function getSafeSkillFileName(name: string): string {
  const safeName = path.basename(name).replace(/[^\w.-]/g, "_");
  return safeName.length > 0 ? safeName : "skill";
}

async function assertSkillRoot(skillPath: string): Promise<string> {
  const lexical = path.resolve(skillPath);
  const parentReal = await fs.promises.realpath(path.dirname(lexical));
  const root = await fs.promises.realpath(lexical);
  // A symlinked skill root bundles whatever it points at, so a repository could
  // commit `.claude/skills/foo -> ~/.claude/skills/foo` and exfiltrate a
  // directory from outside the repo into an uploaded bundle. Only the skill
  // directory itself must be real; symlinked ancestors (e.g. /tmp on macOS)
  // stay legal.
  if (root !== path.join(parentReal, path.basename(lexical))) {
    throw new Error(
      "Local skill bundle root must be a real directory, not a symlink",
    );
  }
  const skillMdPath = path.join(root, "SKILL.md");
  const stat = await fs.promises.stat(skillMdPath);
  if (!stat.isFile()) {
    throw new Error("Local skill bundle must contain a SKILL.md file");
  }
  return root;
}

function isInsideRoot(root: string, candidate: string): boolean {
  const relative = path.relative(root, candidate);
  return (
    Boolean(relative) &&
    !relative.startsWith("..") &&
    !path.isAbsolute(relative)
  );
}

interface SkillFileAccumulator {
  files: Record<string, Uint8Array>;
  totalBytes: number;
}

async function addSkillFile(
  acc: SkillFileAccumulator,
  relativePath: string,
  sourcePath: string,
  size: number,
): Promise<void> {
  if (Object.keys(acc.files).length >= SKILL_BUNDLE_MAX_FILES) {
    throw new Error(
      `Local skill bundle contains more than ${SKILL_BUNDLE_MAX_FILES} files`,
    );
  }
  if (acc.totalBytes + size > SKILL_BUNDLE_MAX_BYTES) {
    throw new Error("Local skill bundle exceeds the 30MB cloud run limit");
  }
  const content = await fs.promises.readFile(sourcePath);
  acc.files[toZipPath(relativePath)] = new Uint8Array(content);
  acc.totalBytes += content.byteLength;
}

async function collectSkillFiles(
  root: string,
  currentDir: string,
  acc: SkillFileAccumulator,
): Promise<void> {
  const entries = await fs.promises.readdir(currentDir, {
    withFileTypes: true,
  });

  for (const entry of entries) {
    if (IGNORED_ENTRIES.has(entry.name)) {
      continue;
    }

    const absolutePath = path.join(currentDir, entry.name);
    const relativePath = path.relative(root, absolutePath);
    if (
      !relativePath ||
      relativePath.startsWith("..") ||
      path.isAbsolute(relativePath)
    ) {
      continue;
    }

    if (entry.isSymbolicLink()) {
      const realPath = await fs.promises
        .realpath(absolutePath)
        .catch(() => null);
      if (!realPath || !isInsideRoot(root, realPath)) {
        continue;
      }
      const stat = await fs.promises.stat(realPath);
      if (!stat.isFile()) {
        continue;
      }
      await addSkillFile(acc, relativePath, realPath, stat.size);
      continue;
    }

    if (entry.isDirectory()) {
      await collectSkillFiles(root, absolutePath, acc);
      continue;
    }

    if (!entry.isFile()) {
      continue;
    }

    const stat = await fs.promises.stat(absolutePath);
    await addSkillFile(acc, relativePath, absolutePath, stat.size);
  }
}

export async function bundleLocalSkill({
  name,
  source,
  skillPath,
}: {
  name: string;
  source: UploadableSkillSource;
  skillPath: string;
}): Promise<BundleLocalSkillOutput> {
  const root = await assertSkillRoot(skillPath);
  const acc: SkillFileAccumulator = { files: {}, totalBytes: 0 };
  await collectSkillFiles(root, root, acc);
  const files = acc.files;
  const fileNames = Object.keys(files).sort();

  if (!files["SKILL.md"]) {
    throw new Error("Local skill bundle must contain a SKILL.md file");
  }

  const manifest = {
    schema_version: 1,
    name,
    source,
  };

  const zipInput: Record<string, Uint8Array> = {};
  for (const fileName of fileNames) {
    zipInput[fileName] = files[fileName];
  }
  zipInput["posthog-skill-bundle.json"] = strToU8(JSON.stringify(manifest));

  const zipped = zipSync(zipInput, { level: 6 });
  if (zipped.byteLength > SKILL_BUNDLE_MAX_BYTES) {
    throw new Error(
      "Local skill bundle archive exceeds the 30MB cloud run limit",
    );
  }

  const contentSha256 = crypto
    .createHash("sha256")
    .update(zipped)
    .digest("hex");

  return {
    name,
    source,
    fileName: `${getSafeSkillFileName(name)}.zip`,
    contentType: "application/zip",
    contentBase64: Buffer.from(zipped).toString("base64"),
    contentSha256,
    size: zipped.byteLength,
  };
}
