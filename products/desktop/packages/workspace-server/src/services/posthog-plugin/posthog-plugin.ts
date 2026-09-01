import { existsSync } from "node:fs";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import {
  ANALYTICS_SERVICE,
  type IAnalytics,
} from "@posthog/platform/analytics";
import { APP_META_SERVICE, type IAppMeta } from "@posthog/platform/app-meta";
import {
  BUNDLED_RESOURCES_SERVICE,
  type IBundledResources,
} from "@posthog/platform/bundled-resources";
import {
  type IStoragePaths,
  STORAGE_PATHS_SERVICE,
} from "@posthog/platform/storage-paths";
import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable, postConstruct, preDestroy } from "inversify";
import { cleanupLegacyCodexMirror, getCodexSkillsDir } from "./codex-mirror";
import {
  overlayDownloadedSkills,
  UpdateSkillsSaga,
} from "./update-skills-saga";

const SKILLS_ZIP_URL = process.env.SKILLS_ZIP_URL ?? "";
const CONTEXT_MILL_ZIP_URL = process.env.CONTEXT_MILL_ZIP_URL ?? "";
const UPDATE_INTERVAL_MS = 30 * 60 * 1000; // 30 minutes
const CODEX_CLEANUP_MARKER = ".codex-mirror-cleanup-done";
const LAST_CHECK_MARKER = ".skills-last-check";

interface PosthogPluginEvents {
  skillsUpdated: true;
}

@injectable()
export class PosthogPluginService extends TypedEventEmitter<PosthogPluginEvents> {
  private intervalId: ReturnType<typeof setInterval> | null = null;
  private lastCheckAt = 0;
  private updating = false;
  private readonly log: ScopedLogger;

  constructor(
    @inject(STORAGE_PATHS_SERVICE)
    private readonly storagePaths: IStoragePaths,
    @inject(BUNDLED_RESOURCES_SERVICE)
    private readonly bundledResources: IBundledResources,
    @inject(ANALYTICS_SERVICE)
    private readonly analytics: IAnalytics,
    @inject(APP_META_SERVICE)
    private readonly appMeta: IAppMeta,
    @inject(ROOT_LOGGER)
    logger: RootLogger,
  ) {
    super();
    this.log = logger.scope("posthog-plugin");
  }

  /** Runtime plugin dir under userData */
  private get runtimePluginDir(): string {
    return join(this.storagePaths.appDataPath, "plugins", "posthog");
  }

  /** Runtime skills cache (downloaded zips extracted here) */
  private get runtimeSkillsDir(): string {
    return join(this.storagePaths.appDataPath, "skills");
  }

  /** Bundled plugin path inside the .vite build output */
  private get bundledPluginDir(): string {
    return this.bundledResources.resolve(".vite/build/plugins/posthog");
  }

  private get lastCheckMarkerPath(): string {
    return join(this.storagePaths.appDataPath, LAST_CHECK_MARKER);
  }

  private async loadPersistedLastCheck(): Promise<number> {
    if (!existsSync(this.runtimeSkillsDir)) return 0;
    try {
      const raw = await readFile(this.lastCheckMarkerPath, "utf-8");
      const ts = Number.parseInt(raw.trim(), 10);
      return Number.isFinite(ts) ? ts : 0;
    } catch {
      return 0;
    }
  }

  private async persistLastCheck(timestampMs: number): Promise<void> {
    try {
      await writeFile(this.lastCheckMarkerPath, `${timestampMs}\n`);
    } catch (err) {
      this.log.warn("Failed to persist skills last-check marker", {
        error: err instanceof Error ? err.message : String(err),
      });
    }
  }

  @postConstruct()
  init(): void {
    this.initialize().catch((err) => {
      this.log.error("Skills initialization failed", { error: err });
      this.analytics.captureException(err, {
        source: "posthog-plugin",
        operation: "initialize",
      });
    });
  }

  private async initialize(): Promise<void> {
    // On first run (or after app update), copy the entire bundled plugin to the runtime dir.
    // On subsequent starts the runtime dir already exists — just overlay any cached downloaded skills.
    if (!existsSync(join(this.runtimePluginDir, "plugin.json"))) {
      await this.copyBundledPlugin();
    }

    // Overlay any previously-downloaded skills on top of the runtime plugin
    await overlayDownloadedSkills(this.runtimeSkillsDir, this.runtimePluginDir);

    await this.cleanupLegacyCodexMirrorOnce();

    this.lastCheckAt = await this.loadPersistedLastCheck();

    // Start periodic updates
    this.intervalId = setInterval(() => {
      this.updateSkills().catch((err) => {
        this.log.warn("Periodic skills update failed", { error: err });
      });
    }, UPDATE_INTERVAL_MS);

    // Kick off first download
    await this.updateSkills();
  }

  /**
   * Removes the skills earlier builds copied into the shared ~/.agents/skills
   * directory (bundled catalog + user-skill mirror), so the directory becomes
   * the user's own again. Runs at most once per install; never fatal.
   */
  private async cleanupLegacyCodexMirrorOnce(): Promise<void> {
    const marker = join(this.storagePaths.appDataPath, CODEX_CLEANUP_MARKER);
    if (existsSync(marker)) {
      return;
    }
    try {
      const removed = await cleanupLegacyCodexMirror(
        getCodexSkillsDir(),
        join(this.getPluginPath(), "skills"),
      );
      if (removed.length > 0) {
        this.log.info("Cleaned legacy mirrored skills from ~/.agents/skills", {
          count: removed.length,
        });
      }
      await writeFile(marker, `${new Date().toISOString()}\n`);
    } catch (err) {
      this.log.warn("Codex mirror cleanup failed", { error: err });
    }
  }

  /**
   * Returns the path to the plugin directory that should be used for agent sessions.
   *
   * - In dev mode: Vite already merged shipped + remote + local-dev skills, so use bundled path.
   * - In prod: use the runtime plugin dir (with downloaded updates).
   * - Fallback: bundled plugin path.
   */
  getPluginPath(): string {
    if (!this.appMeta.isProduction) {
      return this.bundledPluginDir;
    }

    if (existsSync(join(this.runtimePluginDir, "plugin.json"))) {
      return this.runtimePluginDir;
    }

    return this.bundledPluginDir;
  }

  async updateSkills(): Promise<void> {
    const now = Date.now();
    if (now - this.lastCheckAt < UPDATE_INTERVAL_MS) {
      return;
    }

    if (this.updating) {
      return;
    }

    this.updating = true;
    this.lastCheckAt = now;

    const tempDir = join(tmpdir(), `posthog-code-skills-${Date.now()}`);

    try {
      await mkdir(tempDir, { recursive: true });

      const saga = new UpdateSkillsSaga(this.log);
      const result = await saga.run({
        runtimeSkillsDir: this.runtimeSkillsDir,
        runtimePluginDir: this.runtimePluginDir,
        tempDir,
        skillsZipUrl: SKILLS_ZIP_URL,
        contextMillZipUrl: CONTEXT_MILL_ZIP_URL,
        downloadFile: (url, destPath) => this.downloadFile(url, destPath),
      });

      if (result.success) {
        await this.persistLastCheck(now);
        // Only signal listeners when the cache actually changed; an empty
        // download cycle succeeds as a no-op (result.data.updated === false).
        if (result.data.updated) {
          this.emit("skillsUpdated", true);
        }
      } else {
        this.log.warn("Skills update failed", {
          error: result.error,
          failedStep: result.failedStep,
        });
        this.analytics.captureException(new Error(result.error), {
          source: "posthog-plugin",
          operation: "updateSkills",
          failedStep: result.failedStep,
        });
      }
    } catch (err) {
      this.log.warn("Failed to update skills, will retry next interval", {
        error: err,
      });
      this.analytics.captureException(err, {
        source: "posthog-plugin",
        operation: "updateSkills",
      });
    } finally {
      await rm(tempDir, { recursive: true, force: true });
      this.updating = false;
    }
  }

  /**
   * Copies the entire bundled plugin directory to the runtime location.
   * Called once on first run or after an app update.
   */
  private async copyBundledPlugin(): Promise<void> {
    try {
      if (!existsSync(this.bundledPluginDir)) {
        this.log.warn("Bundled plugin dir not found", {
          path: this.bundledPluginDir,
        });
        return;
      }
      await rm(this.runtimePluginDir, { recursive: true, force: true });
      await cp(this.bundledPluginDir, this.runtimePluginDir, {
        recursive: true,
      });
    } catch (err) {
      this.log.warn("Failed to copy bundled plugin", { error: err });
      this.analytics.captureException(err, {
        source: "posthog-plugin",
        operation: "copyBundledPlugin",
      });
    }
  }

  private async downloadFile(url: string, destPath: string): Promise<void> {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(
        `Download failed: ${response.status} ${response.statusText}`,
      );
    }

    const buffer = await response.arrayBuffer();
    await writeFile(destPath, Buffer.from(buffer));
  }

  @preDestroy()
  cleanup(): void {
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }
}
