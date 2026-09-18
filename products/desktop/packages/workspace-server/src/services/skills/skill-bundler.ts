import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { isIgnoredSkillEntry } from "@posthog/shared";
import { strToU8, zipSync } from "fflate";
import type { BundleLocalSkillOutput, UploadableSkillSource } from "./schemas";

const SKILL_BUNDLE_MAX_BYTES = 30 * 1024 * 1024;
const SKILL_BUNDLE_MAX_FILES = 1000;

function toZipPath(filePath: string): string {
  return filePath.split(path.sep).join("/");
}

function getSafeSkillFileName(name: string): string {
  const safeName = path.basename(name).replace(/[^\w.-]/g, "_");
  return safeName.length > 0 ? safeName : "skill";
}

async function assertSkillRoot(
  skillPath: string,
  allowRootSymlink: boolean,
): Promise<string> {
  const lexical = path.resolve(skillPath);
  const parentReal = await fs.promises.realpath(path.dirname(lexical));
  const root = await fs.promises.realpath(lexical);
  if (
    !allowRootSymlink &&
    root !== path.join(parentReal, path.basename(lexical))
  ) {
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

class SkillBundleFileLimitError extends Error {}

/**
 * Generous relative to SKILL_BUNDLE_MAX_FILES so real "too many files"
 * skills still get an exact count; bounds the recount below so a
 * pathologically large committed tree can't turn the error path into
 * unbounded I/O.
 */
const MAX_COUNT_WALK_ENTRIES = SKILL_BUNDLE_MAX_FILES * 50;

/**
 * Counts every non-ignored file per top-level folder. The collection walk
 * stops at the file cap, so counts derived from it reflect readdir order and
 * could name a minor folder while omitting the real offender; this walk runs
 * only when the cap has tripped and reads no file contents. Stops once
 * `maxEntries` directory entries have been visited, so an oversized tree
 * still terminates promptly.
 */
export async function countFilesByTopLevelDir(
  root: string,
  maxEntries = MAX_COUNT_WALK_ENTRIES,
): Promise<Map<string, number>> {
  const counts = new Map<string, number>();
  let visited = 0;
  const walk = async (dir: string, topLevel: string | null): Promise<void> => {
    if (visited >= maxEntries) return;
    const entries = await fs.promises.readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (visited >= maxEntries) return;
      visited++;
      if (
        isIgnoredSkillEntry(
          entry.name,
          entry.isDirectory() ? "directory" : "file",
        )
      ) {
        continue;
      }
      if (entry.isDirectory()) {
        await walk(path.join(dir, entry.name), topLevel ?? entry.name);
      } else if (topLevel && (entry.isFile() || entry.isSymbolicLink())) {
        counts.set(topLevel, (counts.get(topLevel) ?? 0) + 1);
      }
    }
  };
  await walk(root, null);
  return counts;
}

async function tooManyFilesMessage(root: string): Promise<string> {
  const counts = await countFilesByTopLevelDir(root).catch(
    () => new Map<string, number>(),
  );
  const largest = [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([name, count]) => `${name} (${count} files)`)
    .join(", ");
  const hint = largest ? ` Largest folders: ${largest}.` : "";
  return `Local skill bundle contains more than ${SKILL_BUNDLE_MAX_FILES} files.${hint} Remove or move files that are not part of the skill.`;
}

async function addSkillFile(
  acc: SkillFileAccumulator,
  relativePath: string,
  sourcePath: string,
  size: number,
): Promise<void> {
  if (Object.keys(acc.files).length >= SKILL_BUNDLE_MAX_FILES) {
    throw new SkillBundleFileLimitError();
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
    if (
      isIgnoredSkillEntry(
        entry.name,
        entry.isDirectory() ? "directory" : "file",
      )
    ) {
      continue;
    }

    const absolutePath = path.join(currentDir, entry.name);
    const relativePath = path.relative(root, absolutePath);
    if (
      !relativePath ||
      relativePath === ".." ||
      relativePath.startsWith(`..${path.sep}`) ||
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
  allowRootSymlink = false,
}: {
  name: string;
  source: UploadableSkillSource;
  skillPath: string;
  allowRootSymlink?: boolean;
}): Promise<BundleLocalSkillOutput> {
  const root = await assertSkillRoot(skillPath, allowRootSymlink);
  const acc: SkillFileAccumulator = { files: {}, totalBytes: 0 };
  try {
    await collectSkillFiles(root, root, acc);
  } catch (error) {
    if (error instanceof SkillBundleFileLimitError) {
      throw new Error(await tooManyFilesMessage(root));
    }
    throw error;
  }
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
