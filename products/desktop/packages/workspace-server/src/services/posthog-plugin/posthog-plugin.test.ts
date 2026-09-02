import { vol } from "memfs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Set env before module loads (SKILLS_ZIP_URL / CONTEXT_MILL_ZIP_URL are captured at module level)
vi.hoisted(() => {
  process.env.SKILLS_ZIP_URL = "https://example.com/skills.zip";
  process.env.CONTEXT_MILL_ZIP_URL = "https://example.com/context-mill.zip";
});

const mockStoragePaths = vi.hoisted(() => ({
  appDataPath: "/mock/userData",
  logsPath: "/mock/logs",
}));

const mockBundledResources = vi.hoisted(() => ({
  resolve: vi.fn((rel: string) => `/mock/appPath/${rel}`),
  _setPackaged: (packaged: boolean) => {
    mockBundledResources.resolve.mockImplementation((rel: string) =>
      packaged ? `/mock/appPath.unpacked/${rel}` : `/mock/appPath/${rel}`,
    );
  },
}));

const mockAppMeta = vi.hoisted(() => ({
  version: "1.0.0",
  isProduction: false,
}));

const mockAnalytics = vi.hoisted(() => ({
  initialize: vi.fn(),
  track: vi.fn(),
  identify: vi.fn(),
  setCurrentUserId: vi.fn(),
  getCurrentUserId: vi.fn(() => null),
  resetUser: vi.fn(),
  captureException: vi.fn(),
  flush: vi.fn(async () => {}),
  shutdown: vi.fn(async () => {}),
}));

const mockLog = vi.hoisted(() => {
  const scoped = {
    info: vi.fn(),
    error: vi.fn(),
    warn: vi.fn(),
    debug: vi.fn(),
  };
  return { ...scoped, scope: (): typeof scoped => scoped };
});

const mockFetch = vi.hoisted(() => vi.fn());

const mockExtractZip = vi.hoisted(() =>
  vi.fn<(zipPath: string, extractDir: string) => Promise<void>>(async () => {}),
);

vi.mock("node:fs", async () => {
  const { fs } = await import("memfs");
  return { ...fs, default: fs };
});

vi.mock("node:fs/promises", async () => {
  const { fs } = await import("memfs");
  return { ...fs.promises, default: fs.promises };
});

const mockFflateUnzip = vi.hoisted(() => vi.fn());
vi.mock("fflate", () => ({
  unzip: mockFflateUnzip,
}));

vi.mock("./extract-zip", async () => {
  const actual =
    await vi.importActual<typeof import("./extract-zip")>("./extract-zip");
  return {
    ...actual,
    extractZip: mockExtractZip,
  };
});

vi.mock("node:os", () => ({
  homedir: () => "/mock/home",
  tmpdir: () => "/mock/tmp",
  default: { homedir: () => "/mock/home", tmpdir: () => "/mock/tmp" },
}));

import type { RootLogger } from "@posthog/di/logger";
import type { IAnalytics } from "@posthog/platform/analytics";
import type { IAppMeta } from "@posthog/platform/app-meta";
import type { IBundledResources } from "@posthog/platform/bundled-resources";
import type { IStoragePaths } from "@posthog/platform/storage-paths";
import { PosthogPluginService } from "./posthog-plugin";

/** Expose private members for testing without `as any`. */
interface TestablePluginService {
  initialize(): Promise<void>;
  copyBundledPlugin(): Promise<void>;
  intervalId: ReturnType<typeof setInterval> | null;
}

// Paths based on mock values
const RUNTIME_PLUGIN_DIR = "/mock/userData/plugins/posthog";
const RUNTIME_SKILLS_DIR = "/mock/userData/skills";
const BUNDLED_PLUGIN_DIR = "/mock/appPath/.vite/build/plugins/posthog";
const BUNDLED_PLUGIN_DIR_PACKAGED =
  "/mock/appPath.unpacked/.vite/build/plugins/posthog";

function mockFetchResponse(ok: boolean, status = 200) {
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Not Found",
    arrayBuffer: vi.fn(async () => new ArrayBuffer(8)),
  };
}

/** Simulate zip extraction by creating skill files in the extracted dir */
function simulateExtractZip() {
  mockExtractZip.mockImplementation(
    async (zipPath: string, extractDir: string) => {
      if (zipPath.includes("context-mill")) {
        // Inner zip bytes are dummy — fflate.unzip is mocked below.
        vol.mkdirSync(extractDir, { recursive: true });
        vol.writeFileSync(`${extractDir}/omnibus-test-skill.zip`, "dummy");
        vol.writeFileSync(`${extractDir}/manifest.json`, "{}");
        // Non-omnibus zip should be ignored
        vol.writeFileSync(`${extractDir}/other-skill.zip`, "dummy");
      } else {
        // Primary skills zip
        vol.mkdirSync(`${extractDir}/skills/remote-skill`, {
          recursive: true,
        });
        vol.writeFileSync(
          `${extractDir}/skills/remote-skill/SKILL.md`,
          "# Remote",
        );
      }
    },
  );

  mockFflateUnzip.mockImplementation(
    (
      _data: Uint8Array,
      cb: (err: Error | null, data: Record<string, Uint8Array>) => void,
    ) => {
      cb(null, {
        "SKILL.md": new TextEncoder().encode(
          "---\nname: omnibus-test-skill\n---\n# Test Skill",
        ),
      });
    },
  );
}

/** Create the bundled plugin directory in memfs */
function setupBundledPlugin(dir = BUNDLED_PLUGIN_DIR) {
  vol.mkdirSync(`${dir}/skills/shipped-skill`, { recursive: true });
  vol.writeFileSync(`${dir}/plugin.json`, '{"name":"posthog"}');
  vol.writeFileSync(`${dir}/skills/shipped-skill/SKILL.md`, "# Shipped");
}

describe("PosthogPluginService", () => {
  let service: PosthogPluginService;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vol.reset();

    mockBundledResources._setPackaged(false);
    mockAppMeta.isProduction = false;
    mockFetch.mockResolvedValue(mockFetchResponse(true));
    vi.stubGlobal("fetch", mockFetch);
    mockExtractZip.mockResolvedValue(undefined);

    service = new PosthogPluginService(
      mockStoragePaths as unknown as IStoragePaths,
      mockBundledResources as unknown as IBundledResources,
      mockAnalytics as unknown as IAnalytics,
      mockAppMeta as unknown as IAppMeta,
      mockLog as unknown as RootLogger,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    service.cleanup();
    vi.useRealTimers();
  });

  describe("getPluginPath", () => {
    it("returns bundled path in dev mode", () => {
      mockAppMeta.isProduction = false;
      mockBundledResources._setPackaged(false);
      expect(service.getPluginPath()).toBe(BUNDLED_PLUGIN_DIR);
    });

    it("returns runtime path in prod when plugin.json exists", () => {
      mockAppMeta.isProduction = true;
      mockBundledResources._setPackaged(true);
      vol.mkdirSync(RUNTIME_PLUGIN_DIR, { recursive: true });
      vol.writeFileSync(`${RUNTIME_PLUGIN_DIR}/plugin.json`, "{}");

      expect(service.getPluginPath()).toBe(RUNTIME_PLUGIN_DIR);
    });

    it("returns bundled path as fallback in prod", () => {
      mockAppMeta.isProduction = true;
      mockBundledResources._setPackaged(true);
      expect(service.getPluginPath()).toBe(BUNDLED_PLUGIN_DIR_PACKAGED);
    });
  });

  describe("initialize", () => {
    it("copies bundled plugin on first run when plugin.json is missing", async () => {
      setupBundledPlugin();

      await (service as unknown as TestablePluginService).initialize();

      // Entire bundled dir should be copied to runtime
      expect(vol.existsSync(`${RUNTIME_PLUGIN_DIR}/plugin.json`)).toBe(true);
      expect(
        vol.existsSync(`${RUNTIME_PLUGIN_DIR}/skills/shipped-skill/SKILL.md`),
      ).toBe(true);
    });

    it("skips bundled copy when plugin.json already exists in runtime", async () => {
      setupBundledPlugin();
      // Pre-populate runtime dir (simulating previous run)
      vol.mkdirSync(RUNTIME_PLUGIN_DIR, { recursive: true });
      vol.writeFileSync(`${RUNTIME_PLUGIN_DIR}/plugin.json`, '{"old":true}');

      await (service as unknown as TestablePluginService).initialize();

      // Should keep the existing runtime plugin.json, not overwrite
      expect(
        vol.readFileSync(`${RUNTIME_PLUGIN_DIR}/plugin.json`, "utf-8"),
      ).toBe('{"old":true}');
    });

    it("overlays downloaded skills from cache on top of runtime dir", async () => {
      setupBundledPlugin();
      // Pre-populate runtime dir
      vol.mkdirSync(RUNTIME_PLUGIN_DIR, { recursive: true });
      vol.writeFileSync(`${RUNTIME_PLUGIN_DIR}/plugin.json`, "{}");
      // Pre-populate skills cache (as if downloaded previously)
      vol.mkdirSync(`${RUNTIME_SKILLS_DIR}/cached-skill`, { recursive: true });
      vol.writeFileSync(
        `${RUNTIME_SKILLS_DIR}/cached-skill/SKILL.md`,
        "# Cached",
      );

      await (service as unknown as TestablePluginService).initialize();

      expect(
        vol.readFileSync(
          `${RUNTIME_PLUGIN_DIR}/skills/cached-skill/SKILL.md`,
          "utf-8",
        ),
      ).toBe("# Cached");
    });

    it("starts periodic update interval", async () => {
      await (service as unknown as TestablePluginService).initialize();
      expect(
        (service as unknown as TestablePluginService).intervalId,
      ).not.toBeNull();
    });
  });

  describe("updateSkills", () => {
    it("downloads, extracts, and installs skills", async () => {
      setupBundledPlugin();
      simulateExtractZip();

      await service.updateSkills();

      // Skills should be in the runtime cache
      expect(
        vol.existsSync(`${RUNTIME_SKILLS_DIR}/remote-skill/SKILL.md`),
      ).toBe(true);
      expect(mockFetch).toHaveBeenCalledWith("https://example.com/skills.zip");
      expect(mockExtractZip).toHaveBeenCalled();
    });

    it("performs atomic swap of skills directory", async () => {
      setupBundledPlugin();
      // Pre-populate existing cache with old skill
      vol.mkdirSync(`${RUNTIME_SKILLS_DIR}/old-skill`, { recursive: true });
      vol.writeFileSync(`${RUNTIME_SKILLS_DIR}/old-skill/SKILL.md`, "# Old");

      simulateExtractZip();
      await service.updateSkills();

      // New skill should be present, old skill should be gone
      expect(
        vol.existsSync(`${RUNTIME_SKILLS_DIR}/remote-skill/SKILL.md`),
      ).toBe(true);
      expect(vol.existsSync(`${RUNTIME_SKILLS_DIR}/old-skill`)).toBe(false);
      // Temp dirs should be cleaned up
      expect(vol.existsSync(`${RUNTIME_SKILLS_DIR}.new`)).toBe(false);
      expect(vol.existsSync(`${RUNTIME_SKILLS_DIR}.old`)).toBe(false);
    });

    it("overlays new skills into runtime plugin dir", async () => {
      setupBundledPlugin();
      vol.mkdirSync(RUNTIME_PLUGIN_DIR, { recursive: true });
      vol.writeFileSync(`${RUNTIME_PLUGIN_DIR}/plugin.json`, "{}");

      simulateExtractZip();
      await service.updateSkills();

      expect(
        vol.existsSync(`${RUNTIME_PLUGIN_DIR}/skills/remote-skill/SKILL.md`),
      ).toBe(true);
    });

    it("emits 'updated' event on success", async () => {
      simulateExtractZip();
      const handler = vi.fn();
      service.on("skillsUpdated", handler);

      await service.updateSkills();

      expect(handler).toHaveBeenCalledWith(true);
    });

    it("throttles: skips if called within 30 minutes", async () => {
      simulateExtractZip();
      await service.updateSkills();
      mockFetch.mockClear();

      await service.updateSkills();

      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("allows update after throttle period expires", async () => {
      simulateExtractZip();
      await service.updateSkills();
      mockFetch.mockClear();

      vi.advanceTimersByTime(31 * 60 * 1000);
      await service.updateSkills();

      expect(mockFetch).toHaveBeenCalled();
    });

    it("skips if already updating (reentrance guard)", async () => {
      let resolveDownload!: (value: unknown) => void;
      mockFetch.mockReturnValue(
        new Promise((resolve) => {
          resolveDownload = resolve;
        }),
      );

      // Start first update (hangs on fetch)
      const first = service.updateSkills();

      // Advance past throttle so second call reaches the `updating` check
      vi.advanceTimersByTime(31 * 60 * 1000);
      mockFetch.mockClear();
      await service.updateSkills();

      // Second call should not have triggered another fetch
      expect(mockFetch).not.toHaveBeenCalled();

      // Clean up hanging promise
      resolveDownload(mockFetchResponse(true));
      await first.catch(() => {});
    });

    it("downloads and merges context-mill omnibus skills with prefix stripped", async () => {
      setupBundledPlugin();
      simulateExtractZip();

      await service.updateSkills();

      // Omnibus skill should exist with prefix stripped
      expect(vol.existsSync(`${RUNTIME_SKILLS_DIR}/test-skill/SKILL.md`)).toBe(
        true,
      );

      // SKILL.md should have "omnibus-" stripped from name field
      const content = vol.readFileSync(
        `${RUNTIME_SKILLS_DIR}/test-skill/SKILL.md`,
        "utf-8",
      );
      expect(content).toContain("name: test-skill");
      expect(content).not.toContain("omnibus-");
    });

    it("context-mill failure is non-fatal", async () => {
      setupBundledPlugin();
      // Primary skills succeed
      mockExtractZip.mockImplementation(
        async (zipPath: string, extractDir: string) => {
          if (zipPath.includes("context-mill")) {
            throw new Error("context-mill download failed");
          }
          vol.mkdirSync(`${extractDir}/skills/remote-skill`, {
            recursive: true,
          });
          vol.writeFileSync(
            `${extractDir}/skills/remote-skill/SKILL.md`,
            "# Remote",
          );
        },
      );

      const handler = vi.fn();
      service.on("skillsUpdated", handler);
      await service.updateSkills();

      // Primary skills should still be installed
      expect(
        vol.existsSync(`${RUNTIME_SKILLS_DIR}/remote-skill/SKILL.md`),
      ).toBe(true);
      // Update should still succeed
      expect(handler).toHaveBeenCalledWith(true);
    });

    it("handles download failure gracefully", async () => {
      mockFetch.mockRejectedValue(new Error("Network error"));
      await expect(service.updateSkills()).resolves.toBeUndefined();
    });

    it("handles non-ok response gracefully", async () => {
      mockFetch.mockResolvedValue(mockFetchResponse(false, 404));
      await expect(service.updateSkills()).resolves.toBeUndefined();
    });

    it("reports a clear, actionable error when nothing downloads and no cache exists", async () => {
      // Extraction creates no skills directory and there is no pre-existing
      // skills cache to fall back on — the genuine failure case.
      mockExtractZip.mockImplementation(
        async (_zipPath: string, extractDir: string) => {
          vol.mkdirSync(`${extractDir}/random-dir`, { recursive: true });
          vol.writeFileSync(`${extractDir}/random-dir/README.md`, "nope");
        },
      );

      const handler = vi.fn();
      service.on("skillsUpdated", handler);
      await service.updateSkills();

      expect(handler).not.toHaveBeenCalled();
      // The reported error must be the clear, user-useful message, not the
      // opaque "No skills found from any source".
      expect(mockAnalytics.captureException).toHaveBeenCalledTimes(1);
      const reportedError = mockAnalytics.captureException.mock
        .calls[0][0] as Error;
      expect(reportedError.message).not.toContain("No skills found");
      expect(reportedError.message).toContain("Couldn't download skills");
      expect(reportedError.message).toContain("retry automatically");
    });

    it("keeps existing skills and stays silent when a download cycle is empty", async () => {
      // Simulate a previously-downloaded skills cache from an earlier run.
      vol.mkdirSync(`${RUNTIME_SKILLS_DIR}/cached-skill`, { recursive: true });
      vol.writeFileSync(
        `${RUNTIME_SKILLS_DIR}/cached-skill/SKILL.md`,
        "# Cached",
      );

      // Both downloads fail this cycle (e.g. transient network failure).
      mockFetch.mockRejectedValue(new Error("Network error"));

      const handler = vi.fn();
      service.on("skillsUpdated", handler);
      await service.updateSkills();

      // Existing cache is preserved, no false-alarm exception, no update event,
      // and the staging dir is cleaned up.
      expect(
        vol.readFileSync(
          `${RUNTIME_SKILLS_DIR}/cached-skill/SKILL.md`,
          "utf-8",
        ),
      ).toBe("# Cached");
      expect(mockAnalytics.captureException).not.toHaveBeenCalled();
      expect(handler).not.toHaveBeenCalled();
      expect(vol.existsSync(`${RUNTIME_SKILLS_DIR}.new`)).toBe(false);
    });

    it("cleans up temp dir even on error", async () => {
      mockExtractZip.mockRejectedValue(new Error("extraction failed"));

      await service.updateSkills();

      // Temp dir under /mock/tmp should be cleaned up
      const tmpEntries = vol.existsSync("/mock/tmp")
        ? vol.readdirSync("/mock/tmp")
        : [];
      expect(tmpEntries).toHaveLength(0);
    });
  });

  describe("last-check persistence across restarts", () => {
    const MARKER_PATH = "/mock/userData/.skills-last-check";

    function restartService(): PosthogPluginService {
      return new PosthogPluginService(
        mockStoragePaths as unknown as IStoragePaths,
        mockBundledResources as unknown as IBundledResources,
        mockAnalytics as unknown as IAnalytics,
        mockAppMeta as unknown as IAppMeta,
        mockLog as unknown as RootLogger,
      );
    }

    it("writes the last-check marker after a successful update", async () => {
      simulateExtractZip();

      await service.updateSkills();

      expect(vol.existsSync(MARKER_PATH)).toBe(true);
    });

    it("skips the download on restart when the marker is still fresh", async () => {
      setupBundledPlugin();
      simulateExtractZip();
      await service.updateSkills();
      mockFetch.mockClear();

      const restarted = restartService();
      await (restarted as unknown as TestablePluginService).initialize();

      expect(mockFetch).not.toHaveBeenCalled();
      restarted.cleanup();
    });

    it("re-downloads on restart once the interval has expired", async () => {
      setupBundledPlugin();
      simulateExtractZip();
      await service.updateSkills();
      mockFetch.mockClear();

      vi.advanceTimersByTime(31 * 60 * 1000);
      const restarted = restartService();
      await (restarted as unknown as TestablePluginService).initialize();

      expect(mockFetch).toHaveBeenCalled();
      restarted.cleanup();
    });

    it("re-downloads on restart when the skills cache is missing despite a fresh marker", async () => {
      setupBundledPlugin();
      simulateExtractZip();
      vol.mkdirSync("/mock/userData", { recursive: true });
      vol.writeFileSync(MARKER_PATH, `${Date.now()}\n`);

      const restarted = restartService();
      await (restarted as unknown as TestablePluginService).initialize();

      expect(mockFetch).toHaveBeenCalled();
      restarted.cleanup();
    });
  });

  describe("copyBundledPlugin", () => {
    it("copies entire bundled dir to runtime dir", async () => {
      setupBundledPlugin();

      await (service as unknown as TestablePluginService).copyBundledPlugin();

      expect(
        vol.readFileSync(`${RUNTIME_PLUGIN_DIR}/plugin.json`, "utf-8"),
      ).toBe('{"name":"posthog"}');
      expect(
        vol.readFileSync(
          `${RUNTIME_PLUGIN_DIR}/skills/shipped-skill/SKILL.md`,
          "utf-8",
        ),
      ).toBe("# Shipped");
    });

    it("skips if bundled dir does not exist", async () => {
      await (service as unknown as TestablePluginService).copyBundledPlugin();
      expect(vol.existsSync(RUNTIME_PLUGIN_DIR)).toBe(false);
    });

    it("handles copy failure gracefully", async () => {
      // Bundled dir exists but is not a directory (will cause cp to fail or behave oddly)
      // Just verify no exception propagates
      setupBundledPlugin();
      await expect(
        (service as unknown as TestablePluginService).copyBundledPlugin(),
      ).resolves.toBeUndefined();
    });
  });

  describe("cleanup", () => {
    it("clears interval timer", async () => {
      await (service as unknown as TestablePluginService).initialize();
      expect(
        (service as unknown as TestablePluginService).intervalId,
      ).not.toBeNull();

      service.cleanup();
      expect(
        (service as unknown as TestablePluginService).intervalId,
      ).toBeNull();
    });

    it("is safe to call multiple times", () => {
      service.cleanup();
      service.cleanup();
    });
  });
});
