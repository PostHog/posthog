import { execSync } from "node:child_process";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import type { RootLogger } from "@posthog/di/logger";
import { listFilesContainingText } from "@posthog/git/queries";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EnrichmentService } from "./enrichment";
import type { EnrichmentAuth, EnrichmentFileReader } from "./ports";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

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

function authedStub(): EnrichmentAuth {
  return {
    getState: vi.fn(() => ({
      status: "authenticated",
      projectId: 42,
      cloudRegion: "us",
    })),
    getValidAccessToken: vi.fn(async () => ({
      accessToken: "token-x",
      apiHost: "https://us.posthog.com",
    })),
  };
}

function unauthedStub(): EnrichmentAuth {
  return {
    getState: vi.fn(() => ({
      status: "unauthenticated",
      projectId: null,
      cloudRegion: null,
    })),
    getValidAccessToken: vi.fn(),
  };
}

async function writeFile(repoRoot: string, relPath: string, content: string) {
  const abs = path.join(repoRoot, relPath);
  await fs.mkdir(path.dirname(abs), { recursive: true });
  await fs.writeFile(abs, content);
}

function lastCalledResponse(rows: Array<[string, string]>) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => ({ results: rows }),
  };
}

describe("EnrichmentService.findStaleFlagSuggestions", () => {
  let tmp: string;
  let service: EnrichmentService;

  beforeEach(async () => {
    tmp = await fs.mkdtemp(path.join(os.tmpdir(), "posthog-stale-"));
    execSync("git init -q", { cwd: tmp, stdio: "pipe" });
    mockFetch.mockReset();
    service = new EnrichmentService(authedStub(), fileReader, noopLogger);
  });

  afterEach(async () => {
    await fs.rm(tmp, { recursive: true, force: true });
    service.dispose();
  });

  it("returns [] when not authenticated", async () => {
    service.dispose();
    service = new EnrichmentService(unauthedStub(), fileReader, noopLogger);
    const out = await service.findStaleFlagSuggestions(tmp);
    expect(out).toEqual([]);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("returns [] and skips the API call when no flags are referenced in code", async () => {
    await writeFile(tmp, "src/app.ts", `console.log("nothing here");\n`);
    const out = await service.findStaleFlagSuggestions(tmp);
    expect(out).toEqual([]);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("returns [] when every referenced flag has been called recently", async () => {
    mockFetch.mockResolvedValueOnce(
      lastCalledResponse([["some-flag", "2026-04-30T00:00:00Z"]]),
    );
    await writeFile(
      tmp,
      "src/app.ts",
      `import posthog from "posthog-js";\nif (posthog.isFeatureEnabled("some-flag")) console.log("on");\n`,
    );
    const out = await service.findStaleFlagSuggestions(tmp);
    expect(out).toEqual([]);
  });

  it("surfaces flags referenced in code but absent from the last-called response", async () => {
    mockFetch.mockResolvedValueOnce(lastCalledResponse([]));
    await writeFile(
      tmp,
      "src/checkout.ts",
      `import posthog from "posthog-js";\nif (posthog.isFeatureEnabled("old-checkout-flow")) {\n  legacyCheckout();\n}\n`,
    );

    const out = await service.findStaleFlagSuggestions(tmp);
    expect(out).toHaveLength(1);
    expect(out[0].flagKey).toBe("old-checkout-flow");
    expect(out[0].references).toHaveLength(1);
    expect(out[0].references[0].file).toBe("src/checkout.ts");
    expect(out[0].references[0].method).toBe("isFeatureEnabled");
    expect(out[0].referenceCount).toBe(1);
  });

  it("filters out flags that the API confirms were called recently", async () => {
    mockFetch.mockResolvedValueOnce(
      lastCalledResponse([["fresh-flag", "2026-04-30T00:00:00Z"]]),
    );
    await writeFile(
      tmp,
      "src/a.ts",
      `import posthog from "posthog-js";\nif (posthog.isFeatureEnabled("fresh-flag")) {}\nif (posthog.isFeatureEnabled("dusty-flag")) {}\n`,
    );

    const out = await service.findStaleFlagSuggestions(tmp);
    expect(out.map((s) => s.flagKey)).toEqual(["dusty-flag"]);
  });

  it("collects multiple references per flag and reports the total count", async () => {
    mockFetch.mockResolvedValueOnce(lastCalledResponse([]));
    await writeFile(
      tmp,
      "src/a.ts",
      `import posthog from "posthog-js";\nif (posthog.isFeatureEnabled("noisy-flag")) {}\n`,
    );
    await writeFile(
      tmp,
      "src/b.ts",
      `import posthog from "posthog-js";\nconst v = posthog.getFeatureFlag("noisy-flag");\n`,
    );

    const out = await service.findStaleFlagSuggestions(tmp);
    expect(out).toHaveLength(1);
    expect(out[0].referenceCount).toBe(2);
    const files = out[0].references.map((r) => r.file).sort();
    expect(files).toEqual(["src/a.ts", "src/b.ts"]);
  });

  it("posts a HogQL query for the referenced flag keys with the right auth", async () => {
    mockFetch.mockResolvedValueOnce(lastCalledResponse([]));
    await writeFile(
      tmp,
      "src/a.ts",
      `import posthog from "posthog-js";\nif (posthog.isFeatureEnabled("flag-a")) {}\nif (posthog.isFeatureEnabled("flag-b")) {}\n`,
    );

    await service.findStaleFlagSuggestions(tmp);

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toContain("/api/projects/42/query/");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("Bearer token-x");
    const body = JSON.parse(init.body);
    expect(body.query.kind).toBe("HogQLQuery");
    expect(body.query.values.flagKeys.sort()).toEqual(["flag-a", "flag-b"]);
  });

  it("returns [] when the directory isn't a git repo", async () => {
    const nonGit = await fs.mkdtemp(path.join(os.tmpdir(), "non-git-stale-"));
    try {
      const out = await service.findStaleFlagSuggestions(nonGit);
      expect(out).toEqual([]);
      expect(mockFetch).not.toHaveBeenCalled();
    } finally {
      await fs.rm(nonGit, { recursive: true, force: true });
    }
  });
});
