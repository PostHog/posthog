import { execSync } from "node:child_process";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { RootLogger } from "@posthog/di/logger";
import { listFilesContainingText } from "@posthog/git/queries";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EnrichmentService } from "./enrichment";
import type { EnrichmentAuth, EnrichmentFileReader } from "./ports";

const stubAuthService: EnrichmentAuth = {
  getState: vi.fn(() => ({
    status: "unauthenticated",
    projectId: null,
    cloudRegion: null,
  })),
  getValidAccessToken: vi.fn(),
};

const fileReader: EnrichmentFileReader = {
  stat: (p) => fs.stat(p).then((s) => ({ size: s.size })),
  readFile: (p) => fs.readFile(p, "utf-8"),
  listFilesContainingText: (repoPath, text) =>
    listFilesContainingText(repoPath, text),
};

const noopLogger: RootLogger = {
  debug: () => {},
  info: () => {},
  warn: () => {},
  error: () => {},
  scope: () => noopLogger,
};

async function writeFile(repoRoot: string, relPath: string, content: string) {
  const abs = path.join(repoRoot, relPath);
  await fs.mkdir(path.dirname(abs), { recursive: true });
  await fs.writeFile(abs, content);
}

describe("EnrichmentService.detectPosthogInstallState", () => {
  let tmp: string;
  let service: EnrichmentService;

  beforeEach(async () => {
    tmp = await fs.mkdtemp(path.join(os.tmpdir(), "posthog-detect-"));
    execSync("git init -q", { cwd: tmp, stdio: "pipe" });
    service = new EnrichmentService(stubAuthService, fileReader, noopLogger);
  });

  afterEach(async () => {
    await fs.rm(tmp, { recursive: true, force: true });
    service.dispose();
  });

  it("returns not_installed for an empty repo", async () => {
    expect(await service.detectPosthogInstallState(tmp)).toBe("not_installed");
  });

  it("returns installed_no_init when package.json declares posthog-js but no init call exists", async () => {
    await writeFile(
      tmp,
      "package.json",
      JSON.stringify({
        name: "test-app",
        dependencies: { "posthog-js": "^1.0.0" },
      }),
    );
    expect(await service.detectPosthogInstallState(tmp)).toBe(
      "installed_no_init",
    );
  });

  it("returns initialized when an entry-point file calls posthog.init()", async () => {
    await writeFile(
      tmp,
      "package.json",
      JSON.stringify({
        name: "test-app",
        dependencies: { "posthog-js": "^1.0.0" },
      }),
    );
    await writeFile(
      tmp,
      "pages/_app.tsx",
      `import posthog from "posthog-js";\nposthog.init("phc_xxx", { api_host: "https://app.posthog.com" });\nexport default function App() { return null; }\n`,
    );
    expect(await service.detectPosthogInstallState(tmp)).toBe("initialized");
  });

  it("returns initialized when posthog is used in a non-standard path (apps/dashboard/src/bootstrap.ts)", async () => {
    await writeFile(
      tmp,
      "package.json",
      JSON.stringify({
        name: "monorepo-root",
      }),
    );
    await writeFile(
      tmp,
      "apps/dashboard/package.json",
      JSON.stringify({
        name: "dashboard",
        dependencies: { "posthog-js": "^1.0.0" },
      }),
    );
    await writeFile(
      tmp,
      "apps/dashboard/src/bootstrap.ts",
      `import posthog from "posthog-js";\nposthog.init(import.meta.env.VITE_POSTHOG_KEY);\nposthog.capture("app_loaded");\n`,
    );
    expect(await service.detectPosthogInstallState(tmp)).toBe("initialized");
  });

  it("picks up monorepo manifests in subdirectories (apps/api/requirements.txt)", async () => {
    await writeFile(tmp, "package.json", JSON.stringify({ name: "monorepo" }));
    await writeFile(
      tmp,
      "apps/api/requirements.txt",
      "django==5.0\nposthog==3.5.0\n",
    );
    expect(await service.detectPosthogInstallState(tmp)).toBe(
      "installed_no_init",
    );
  });

  it("returns initialized when a Python entry point uses posthog", async () => {
    await writeFile(tmp, "requirements.txt", "posthog==3.5.0\n");
    await writeFile(
      tmp,
      "src/myapp/main.py",
      `import os\nimport posthog\n\nposthog.api_key = os.environ["POSTHOG_KEY"]\nposthog.host = "https://app.posthog.com"\nposthog.capture("user-id", "user_signed_up")\n`,
    );
    expect(await service.detectPosthogInstallState(tmp)).toBe("initialized");
  });

  it("returns installed_no_init for a Ruby repo with a Gemfile declaring posthog", async () => {
    await writeFile(
      tmp,
      "Gemfile",
      `source "https://rubygems.org"\ngem "posthog-ruby"\n`,
    );
    expect(await service.detectPosthogInstallState(tmp)).toBe(
      "installed_no_init",
    );
  });

  it("ignores files inside skip-paths like node_modules when scanning for init calls", async () => {
    await writeFile(
      tmp,
      "package.json",
      JSON.stringify({
        name: "test-app",
        dependencies: { "posthog-js": "^1.0.0" },
      }),
    );
    await writeFile(
      tmp,
      "node_modules/some-other-pkg/dist/index.js",
      `posthog.init("phc_xxx");\n`,
    );
    expect(await service.detectPosthogInstallState(tmp)).toBe(
      "installed_no_init",
    );
  });

  it("treats init-only-with-env-var (no capture) as installed_no_init", async () => {
    await writeFile(
      tmp,
      "package.json",
      JSON.stringify({ dependencies: { "posthog-js": "^1.0.0" } }),
    );
    await writeFile(
      tmp,
      "src/bootstrap.ts",
      `import posthog from "posthog-js";\nposthog.init(import.meta.env.VITE_POSTHOG_KEY);\n`,
    );
    expect(await service.detectPosthogInstallState(tmp)).toBe(
      "installed_no_init",
    );
  });

  it("returns not_installed for empty/missing repoPath", async () => {
    expect(await service.detectPosthogInstallState("")).toBe("not_installed");
  });

  it("returns not_installed when the directory isn't a git repo", async () => {
    const nonGitDir = await fs.mkdtemp(path.join(os.tmpdir(), "non-git-"));
    try {
      await writeFile(
        nonGitDir,
        "package.json",
        JSON.stringify({ dependencies: { "posthog-js": "^1.0.0" } }),
      );
      expect(await service.detectPosthogInstallState(nonGitDir)).toBe(
        "not_installed",
      );
    } finally {
      await fs.rm(nonGitDir, { recursive: true, force: true });
    }
  });
});
