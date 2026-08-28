import * as fs from "node:fs";
import * as path from "node:path";
import { isIgnoredSkillPath, SKILL_EXISTS_MARKER } from "@posthog/shared";
import type { Unzipped } from "fflate";
import { injectable } from "inversify";
import { unzipAsync } from "../posthog-plugin/extract-zip";
import { getUserSkillsDir, isProbablyText } from "../skills/skill-discovery";
import { validateSkillDirName } from "../skills/skills";
import {
  type MarketplacePreviewFile,
  type MarketplacePreviewOutput,
  type MarketplaceSearchOutput,
  type MarketplaceSkillRef,
  skillsShSearchResponse,
} from "./schemas";

const SKILLS_SH_SEARCH_URL = "https://skills.sh/api/search";
const REPO_SOURCE_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
// SHAs, tags, and slashless branch names; anything else could rewrite the
// codeload URL path.
const GIT_REF_PATTERN = /^[A-Za-z0-9_.-]+$/;
const MAX_ARCHIVE_BYTES = 100 * 1024 * 1024;
const MAX_UNZIPPED_BYTES = 500 * 1024 * 1024;
const MAX_PREVIEW_FILE_BYTES = 256 * 1024;
const ARCHIVE_CACHE_TTL_MS = 5 * 60_000;
const ARCHIVE_CACHE_MAX_ENTRIES = 4;
const SEARCH_TIMEOUT_MS = 10_000;
const POPULAR_SEED_QUERIES = ["code", "git", "review", "test", "docs", "web"];
const POPULAR_LIMIT = 40;
const POPULAR_CACHE_TTL_MS = 30 * 60_000;
const ARCHIVE_DOWNLOAD_TIMEOUT_MS = 60_000;

interface InstalledSkillsFile {
  version: number;
  installed: Record<string, { repo: string }>;
}

interface CachedArchive {
  fetchedAt: number;
  entries: Unzipped;
}

function installedStatePath(): string {
  return path.join(getUserSkillsDir(), "installed.json");
}

/**
 * Reads the versioned install-state file. Its only purpose is the
 * "Installed" badge in browse results — installs are copy-and-forget.
 */
export async function readInstalledState(): Promise<InstalledSkillsFile> {
  try {
    const content = await fs.promises.readFile(installedStatePath(), "utf-8");
    const data = JSON.parse(content) as InstalledSkillsFile;
    if (!data.installed || typeof data.installed !== "object") {
      return { version: 1, installed: {} };
    }
    return { version: 1, installed: data.installed };
  } catch {
    return { version: 1, installed: {} };
  }
}

async function writeInstalledState(state: InstalledSkillsFile): Promise<void> {
  await fs.promises.mkdir(getUserSkillsDir(), { recursive: true });
  await fs.promises.writeFile(
    installedStatePath(),
    `${JSON.stringify(state, null, 2)}\n`,
    "utf-8",
  );
}

/**
 * Finds the archive prefix of the directory named `skillId` that contains a
 * SKILL.md, e.g. "repo-HEAD/skills/commit/". Prefers the shallowest match.
 */
export function findSkillDirPrefix(
  entries: Unzipped,
  skillId: string,
): string | null {
  const suffix = `/${skillId}/SKILL.md`;
  const matches = Object.keys(entries)
    .filter((key) => key.endsWith(suffix))
    .sort((a, b) => a.split("/").length - b.split("/").length);
  const match = matches[0];
  if (!match) return null;
  return match.slice(0, match.length - "SKILL.md".length);
}

/** Rejects zip entries that would escape the install directory (zip-slip). */
function isSafeRelativePath(relPath: string): boolean {
  if (relPath.length === 0 || relPath.includes("\\")) return false;
  const segments = relPath.split("/");
  return segments.every(
    (segment) => segment.length > 0 && segment !== "." && segment !== "..",
  );
}

export function collectSkillFiles(
  entries: Unzipped,
  prefix: string,
): Map<string, Uint8Array> {
  const files = new Map<string, Uint8Array>();
  for (const [key, bytes] of Object.entries(entries)) {
    if (!key.startsWith(prefix) || key.endsWith("/")) continue;
    const relPath = key.slice(prefix.length);
    if (!isSafeRelativePath(relPath) || isIgnoredSkillPath(relPath)) continue;
    files.set(relPath, bytes);
  }
  return files;
}

@injectable()
export class SkillsMarketplaceService {
  private archives = new Map<string, CachedArchive>();
  private popularCache: {
    fetchedAt: number;
    output: MarketplaceSearchOutput;
  } | null = null;

  async popular(): Promise<MarketplaceSearchOutput> {
    const cached = this.popularCache;
    if (cached && Date.now() - cached.fetchedAt < POPULAR_CACHE_TTL_MS) {
      return cached.output;
    }

    const batches = await Promise.allSettled(
      POPULAR_SEED_QUERIES.map((query) => this.search(query)),
    );
    const byId = new Map<string, MarketplaceSearchOutput["results"][number]>();
    for (const batch of batches) {
      if (batch.status !== "fulfilled") continue;
      for (const result of batch.value.results) {
        byId.set(result.id, result);
      }
    }
    if (byId.size === 0) {
      throw new Error("skills.sh search failed for every seed query");
    }

    const output = {
      results: [...byId.values()]
        .sort((a, b) => b.installs - a.installs)
        .slice(0, POPULAR_LIMIT),
    };
    this.popularCache = { fetchedAt: Date.now(), output };
    return output;
  }

  async search(query: string): Promise<MarketplaceSearchOutput> {
    const trimmed = query.trim();
    if (trimmed.length < 2) return { results: [] };

    const url = new URL(SKILLS_SH_SEARCH_URL);
    url.searchParams.set("q", trimmed);
    const response = await fetch(url, {
      signal: AbortSignal.timeout(SEARCH_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw new Error(`skills.sh search failed: ${response.status}`);
    }
    const data = skillsShSearchResponse.parse(await response.json());
    const state = await readInstalledState();

    return {
      results: data.skills.map((skill) => ({
        id: skill.id,
        skillId: skill.skillId,
        name: skill.name,
        installs: skill.installs ?? 0,
        source: skill.source,
        installed: skill.skillId in state.installed,
      })),
    };
  }

  async preview(ref: MarketplaceSkillRef): Promise<MarketplacePreviewOutput> {
    const files = await this.getSkillFiles(ref);

    const previewFiles: MarketplacePreviewFile[] = [...files.entries()]
      .map(([relPath, bytes]) => ({
        path: relPath,
        size: bytes.byteLength,
        content:
          bytes.byteLength <= MAX_PREVIEW_FILE_BYTES && isProbablyText(bytes)
            ? new TextDecoder().decode(bytes)
            : null,
      }))
      .sort((a, b) => {
        if (a.path === "SKILL.md") return -1;
        if (b.path === "SKILL.md") return 1;
        return a.path.localeCompare(b.path);
      });

    return {
      files: previewFiles,
      hasScripts: previewFiles.some((f) => f.path.startsWith("scripts/")),
    };
  }

  /**
   * Copy-and-forget install: extract the skill directory into
   * ~/.claude/skills/<skillId>. From then on it is an ordinary, editable
   * user skill; installed.json only feeds the "Installed" badge.
   */
  async install(
    ref: MarketplaceSkillRef,
    overwrite = false,
  ): Promise<{ path: string }> {
    validateSkillDirName(ref.skillId);
    const target = path.join(getUserSkillsDir(), ref.skillId);
    if (fs.existsSync(target) && !overwrite) {
      throw new Error(
        `A skill named "${ref.skillId}" ${SKILL_EXISTS_MARKER}. Reinstalling will replace your local version.`,
      );
    }

    const files = await this.getSkillFiles(ref);

    if (fs.existsSync(target)) {
      await fs.promises.rm(target, { recursive: true, force: true });
    }
    for (const [relPath, bytes] of files) {
      const filePath = path.join(target, relPath);
      await fs.promises.mkdir(path.dirname(filePath), { recursive: true });
      await fs.promises.writeFile(filePath, bytes);
    }

    const state = await readInstalledState();
    state.installed[ref.skillId] = { repo: ref.source };
    await writeInstalledState(state);

    return { path: target };
  }

  private async getSkillFiles(
    ref: MarketplaceSkillRef,
  ): Promise<Map<string, Uint8Array>> {
    const entries = await this.getRepoArchive(ref.source, ref.ref);
    const prefix = findSkillDirPrefix(entries, ref.skillId);
    if (!prefix) {
      throw new Error(`Skill "${ref.skillId}" was not found in ${ref.source}`);
    }
    const files = collectSkillFiles(entries, prefix);
    if (!files.has("SKILL.md")) {
      throw new Error(
        `Skill "${ref.skillId}" in ${ref.source} has no SKILL.md`,
      );
    }
    return files;
  }

  private async getRepoArchive(
    source: string,
    gitRef?: string,
  ): Promise<Unzipped> {
    if (!REPO_SOURCE_PATTERN.test(source)) {
      throw new Error(`Invalid repository reference: ${source}`);
    }
    if (gitRef !== undefined && !GIT_REF_PATTERN.test(gitRef)) {
      throw new Error(`Invalid git ref: ${gitRef}`);
    }

    const cacheKey = `${source}@${gitRef ?? "HEAD"}`;
    const cached = this.archives.get(cacheKey);
    if (cached && Date.now() - cached.fetchedAt < ARCHIVE_CACHE_TTL_MS) {
      // LRU: refresh recency on hit.
      this.archives.delete(cacheKey);
      this.archives.set(cacheKey, cached);
      return cached.entries;
    }

    const response = await fetch(
      `https://codeload.github.com/${source}/zip/${gitRef ?? "HEAD"}`,
      { signal: AbortSignal.timeout(ARCHIVE_DOWNLOAD_TIMEOUT_MS) },
    );
    if (!response.ok) {
      throw new Error(`Failed to download ${source}: ${response.status}`);
    }
    const declaredBytes = Number(response.headers.get("content-length") ?? 0);
    if (declaredBytes > MAX_ARCHIVE_BYTES) {
      throw new Error(`Repository ${source} is too large to download`);
    }
    // codeload responses are chunked; the cap is enforced while streaming.
    const buffer = await readBodyWithLimit(response, MAX_ARCHIVE_BYTES, source);
    const entries = await unzipWithLimit(buffer, MAX_UNZIPPED_BYTES, source);

    this.archives.set(cacheKey, { fetchedAt: Date.now(), entries });
    while (this.archives.size > ARCHIVE_CACHE_MAX_ENTRIES) {
      const oldest = this.archives.keys().next().value;
      if (oldest === undefined) break;
      this.archives.delete(oldest);
    }
    return entries;
  }
}

async function readBodyWithLimit(
  response: Response,
  maxBytes: number,
  source: string,
): Promise<Uint8Array> {
  const tooLarge = () =>
    new Error(`Repository ${source} is too large to download`);
  const reader = response.body?.getReader();
  if (!reader) {
    const buffer = new Uint8Array(await response.arrayBuffer());
    if (buffer.byteLength > maxBytes) throw tooLarge();
    return buffer;
  }

  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      throw tooLarge();
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
}

/** Inflates the archive within a decompressed-bytes budget (zip-bomb guard). */
export function unzipWithLimit(
  data: Uint8Array,
  maxTotalBytes: number,
  source: string,
): Promise<Unzipped> {
  let total = 0;
  let exceeded = false;
  return unzipAsync(data, {
    filter: (file) => {
      total += file.originalSize;
      if (total > maxTotalBytes) exceeded = true;
      return !exceeded;
    },
  }).then((entries) => {
    if (exceeded) {
      throw new Error(`Repository ${source} is too large to unpack`);
    }
    return entries;
  });
}
