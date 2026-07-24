import { createHash } from "node:crypto";
import * as path from "node:path";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import {
  EXT_TO_LANG_ID,
  enrichSource,
  type ParseResult,
  PostHogApi,
  PostHogEnricher,
  type SerializedEnrichment,
  setLogger as setEnricherLogger,
  toSerializable,
} from "@posthog/enricher";
import { inject, injectable } from "inversify";
import { ENRICHMENT_AUTH, ENRICHMENT_FILE_READER } from "./identifiers";
import type { EnrichmentAuth, EnrichmentFileReader } from "./ports";

export type PosthogInstallState =
  | "not_installed"
  | "installed_no_init"
  | "initialized";

const MAX_CACHE_ENTRIES = 200;
const CACHE_TTL_MS = 10 * 60 * 1000;

interface CacheEntry {
  value: SerializedEnrichment | null;
  expiresAt: number;
}

export interface EnrichFileInput {
  taskId: string;
  filePath: string;
  absolutePath?: string;
  content: string;
}

const MANIFEST_BASENAMES = new Set([
  "package.json",
  "requirements.txt",
  "pyproject.toml",
  "Gemfile",
  "Podfile",
  "build.gradle",
  "build.gradle.kts",
  "pubspec.yaml",
  "pubspec.yml",
  "go.mod",
  "composer.json",
]);
const MANIFEST_EXTENSIONS = new Set([".csproj"]);

const SKIP_PATH_SEGMENTS = new Set([
  "node_modules",
  "dist",
  "build",
  "out",
  ".next",
  ".nuxt",
  ".svelte-kit",
  ".turbo",
  ".cache",
  "vendor",
  "target",
  "coverage",
  ".git",
  "__pycache__",
  ".venv",
  "venv",
  "env",
  ".tox",
]);

export interface StaleFlagSuggestion {
  flagKey: string;
  references: { file: string; line: number; method: string }[];
  referenceCount: number;
}

const STALE_FLAG_SUGGESTION_CAP = 4;
const STALE_FLAG_REFERENCES_PER_FLAG = 5;
const STALE_LOOKBACK_DAYS = 30;

const MAX_FILE_BYTES = 256 * 1024;
const MAX_FILES_TO_PARSE = 500;

interface ParsedRepoEntry {
  langId: string;
  result: ParseResult | null;
}

interface ParsedRepoCacheEntry {
  files: Map<string, ParsedRepoEntry>;
  manifestHit: boolean;
}

function yieldToEventLoop(): Promise<void> {
  return new Promise<void>((resolve) => setImmediate(resolve));
}

function shouldSkipPath(relPath: string): boolean {
  const parts = relPath.split(/[\\/]/);
  return parts.some((segment) => SKIP_PATH_SEGMENTS.has(segment));
}

function isManifestPath(relPath: string): boolean {
  const base = path.basename(relPath);
  if (MANIFEST_BASENAMES.has(base)) return true;
  const ext = path.extname(relPath).toLowerCase();
  return MANIFEST_EXTENSIONS.has(ext);
}

function isUsageProbeCandidate(relPath: string): boolean {
  if (shouldSkipPath(relPath)) return false;
  const ext = path.extname(relPath).toLowerCase();
  if (!ext) return false;
  return ext in EXT_TO_LANG_ID;
}

@injectable()
export class EnrichmentService {
  private enricher: PostHogEnricher | null = null;
  private readonly cache = new Map<string, CacheEntry>();
  private readonly repoScanCache = new Map<string, ParsedRepoCacheEntry>();
  private readonly repoScanInflight = new Map<
    string,
    Promise<ParsedRepoCacheEntry | null>
  >();
  private readonly log: ScopedLogger;

  constructor(
    @inject(ENRICHMENT_AUTH)
    private readonly authService: EnrichmentAuth,
    @inject(ENRICHMENT_FILE_READER)
    private readonly files: EnrichmentFileReader,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
  ) {
    this.log = logger.scope("enrichment-service");
    setEnricherLogger({
      warn: (message: string, ...args: unknown[]) =>
        this.log.warn(message, ...args),
    });
  }

  async enrichFile(
    input: EnrichFileInput,
  ): Promise<SerializedEnrichment | null> {
    const { taskId, filePath, absolutePath, content } = input;
    const cacheKey = this.buildCacheKey(taskId, filePath, content);

    const cached = this.cache.get(cacheKey);
    const now = Date.now();
    if (cached && cached.expiresAt > now) {
      this.cache.delete(cacheKey);
      this.cache.set(cacheKey, cached);
      return cached.value;
    }
    if (cached) {
      this.cache.delete(cacheKey);
    }

    const result = await this.runEnrichment(filePath, absolutePath, content);
    this.setCache(cacheKey, result);
    return result;
  }

  private async runEnrichment(
    filePath: string,
    absolutePath: string | undefined,
    content: string,
  ): Promise<SerializedEnrichment | null> {
    const apiConfig = await this.resolveApiConfig();
    if (!apiConfig) return null;

    const enricher = this.getEnricher();
    const enriched = await enrichSource({
      enricher,
      apiConfig,
      filePath,
      absolutePath,
      content,
      onDebug: (message: string, data?: Record<string, unknown>) => {
        this.log.debug(message, { filePath, ...(data ?? {}) });
      },
    });

    if (!enriched) return null;
    return toSerializable(enriched);
  }

  private getEnricher(): PostHogEnricher {
    if (!this.enricher) {
      this.enricher = new PostHogEnricher();
    }
    return this.enricher;
  }

  private async resolveApiConfig(): Promise<{
    apiKey: string;
    host: string;
    projectId: number;
  } | null> {
    const state = this.authService.getState();
    if (
      state.status !== "authenticated" ||
      !state.projectId ||
      !state.cloudRegion
    ) {
      return null;
    }
    try {
      const auth = await this.authService.getValidAccessToken();
      return {
        apiKey: auth.accessToken,
        host: auth.apiHost,
        projectId: state.projectId,
      };
    } catch (err) {
      this.log.debug("Failed to resolve access token", {
        message: err instanceof Error ? err.message : String(err),
      });
      return null;
    }
  }

  async detectPosthogInstallState(
    repoPath: string,
  ): Promise<PosthogInstallState> {
    if (!repoPath) return "not_installed";

    const scan = await this.scanRepo(repoPath);
    if (!scan) return "not_installed";

    let usageFound = false;
    for (const entry of scan.files.values()) {
      if (!entry.result) continue;
      if (entry.result.calls.length > 0 || entry.result.initCalls.length > 0) {
        usageFound = true;
        break;
      }
    }

    if (usageFound) return "initialized";
    if (scan.manifestHit) return "installed_no_init";
    return "not_installed";
  }

  async findStaleFlagSuggestions(
    repoPath: string,
  ): Promise<StaleFlagSuggestion[]> {
    if (!repoPath) return [];

    const apiConfig = await this.resolveApiConfig();
    if (!apiConfig) return [];

    const scan = await this.scanRepo(repoPath);
    if (!scan) return [];

    const referencesByKey = new Map<
      string,
      { file: string; line: number; method: string }[]
    >();
    for (const [relPath, entry] of scan.files) {
      if (!entry.result) continue;
      for (const check of entry.result.flagChecks) {
        const list = referencesByKey.get(check.flagKey) ?? [];
        list.push({ file: relPath, line: check.line, method: check.method });
        referencesByKey.set(check.flagKey, list);
      }
    }

    if (referencesByKey.size === 0) return [];

    const flagKeys = [...referencesByKey.keys()];
    let lastCalled: Map<string, string>;
    try {
      const api = new PostHogApi(apiConfig);
      lastCalled = await api.getFlagLastCalled(flagKeys, STALE_LOOKBACK_DAYS);
    } catch (err) {
      this.log.debug("Failed to fetch flag-call timestamps", {
        error: err instanceof Error ? err.message : String(err),
      });
      return [];
    }

    const staleKeys = flagKeys.filter((key) => !lastCalled.has(key)).sort();

    const suggestions: StaleFlagSuggestion[] = [];
    for (const key of staleKeys) {
      const refs = referencesByKey.get(key);
      if (!refs || refs.length === 0) continue;
      suggestions.push({
        flagKey: key,
        references: refs.slice(0, STALE_FLAG_REFERENCES_PER_FLAG),
        referenceCount: refs.length,
      });
      if (suggestions.length >= STALE_FLAG_SUGGESTION_CAP) break;
    }
    return suggestions;
  }

  // Memoized per repoPath; concurrent callers wait on the same in-flight
  // promise. Cleared by `dispose()`.
  private async scanRepo(
    repoPath: string,
  ): Promise<ParsedRepoCacheEntry | null> {
    const cached = this.repoScanCache.get(repoPath);
    if (cached) return cached;

    const inflight = this.repoScanInflight.get(repoPath);
    if (inflight) return inflight;

    const promise = this.runScan(repoPath).finally(() => {
      this.repoScanInflight.delete(repoPath);
    });
    this.repoScanInflight.set(repoPath, promise);
    return promise;
  }

  private async runScan(
    repoPath: string,
  ): Promise<ParsedRepoCacheEntry | null> {
    let posthogFiles: string[];
    try {
      posthogFiles = await this.files.listFilesContainingText(
        repoPath,
        "posthog",
      );
    } catch (err) {
      this.log.debug("git grep failed during repo scan", {
        repoPath,
        error: err instanceof Error ? err.message : String(err),
      });
      return null;
    }

    const enricher = this.getEnricher();
    const langIdMap = EXT_TO_LANG_ID as Record<string, string | undefined>;

    const manifestHit = posthogFiles.some(isManifestPath);

    const toParse: { relPath: string; langId: string }[] = [];
    for (const relPath of posthogFiles) {
      if (!isUsageProbeCandidate(relPath)) continue;
      const ext = path.extname(relPath).toLowerCase();
      const langId = langIdMap[ext];
      if (!langId || !enricher.isSupported(langId)) continue;
      toParse.push({ relPath, langId });
      if (toParse.length >= MAX_FILES_TO_PARSE) {
        this.log.info("Capping repo parse to keep main process responsive", {
          repoPath,
          totalCandidates: posthogFiles.length,
          parseLimit: MAX_FILES_TO_PARSE,
        });
        break;
      }
    }

    const files = new Map<string, ParsedRepoEntry>();
    for (const candidate of toParse) {
      const absPath = path.join(repoPath, candidate.relPath);
      let content: string;
      try {
        const stat = await this.files.stat(absPath);
        if (stat.size > MAX_FILE_BYTES) {
          files.set(candidate.relPath, {
            langId: candidate.langId,
            result: null,
          });
          continue;
        }
        content = await this.files.readFile(absPath);
      } catch {
        continue;
      }
      try {
        const result = await enricher.parse(content, candidate.langId);
        files.set(candidate.relPath, { langId: candidate.langId, result });
      } catch (err) {
        this.log.debug("enricher.parse threw during repo scan, skipping file", {
          file: candidate.relPath,
          error: err instanceof Error ? err.message : String(err),
        });
        files.set(candidate.relPath, {
          langId: candidate.langId,
          result: null,
        });
      }
      await yieldToEventLoop();
    }

    const entry: ParsedRepoCacheEntry = { files, manifestHit };
    this.repoScanCache.set(repoPath, entry);
    return entry;
  }

  private buildCacheKey(
    taskId: string,
    filePath: string,
    content: string,
  ): string {
    const hash = createHash("sha1").update(content).digest("hex");
    return `${taskId}::${filePath}::${hash}`;
  }

  private setCache(key: string, value: SerializedEnrichment | null): void {
    this.cache.set(key, { value, expiresAt: Date.now() + CACHE_TTL_MS });
    while (this.cache.size > MAX_CACHE_ENTRIES) {
      const oldest = this.cache.keys().next().value;
      if (oldest === undefined) break;
      this.cache.delete(oldest);
    }
  }

  dispose(): void {
    this.enricher?.dispose();
    this.enricher = null;
    this.cache.clear();
    this.repoScanCache.clear();
    this.repoScanInflight.clear();
  }
}
