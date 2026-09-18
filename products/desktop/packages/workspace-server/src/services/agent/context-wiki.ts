import * as fs from "node:fs";
import * as path from "node:path";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import type { ReadableStream as WebReadableStream } from "node:stream/web";
import { execGit } from "@posthog/git/git-exec";
import type { AgentScopedLogger } from "./ports";

const API_TIMEOUT_MS = 10_000;
const BUNDLE_DOWNLOAD_TIMEOUT_MS = 60_000;
const GIT_TIMEOUT_MS = 60_000;
// The server bounds a wiki at 50MB of content; a bundle materially above that
// is not a wiki, so stop the download instead of filling the disk.
const MAX_BUNDLE_BYTES = 200_000_000;
// A checkout is only pruned once no session plausibly still reads it.
const STALE_CHECKOUT_MS = 24 * 60 * 60 * 1000;

export type AuthenticatedFetch = (
  input: string,
  init?: RequestInit,
) => Promise<Response>;

export interface ContextWikiMount {
  /** Local checkout of the org's wiki, for POSTHOG_CONTEXT_LAYER_PATH. */
  path: string;
  /** API path agents land commits through, for POSTHOG_CONTEXT_LAYER_COMMITS_PATH. */
  commitsPath: string;
}

// A project's organization never changes, so one lookup per process is enough.
const organizationIds = new Map<string, string>();

// One mount per org per process: concurrent session starts share the same
// clone, so they must also share the in-flight preparation — a second caller
// must not rm -rf the checkout a first caller's session is about to use.
const inflight = new Map<string, Promise<ContextWikiMount | null>>();

/**
 * Clones the organization's context wiki onto local disk for desktop sessions,
 * mirroring what the cloud sandbox mount does at provisioning.
 *
 * Best-effort by design: any failure (wiki not enabled, flag off, network,
 * git) returns null so a session never fails or stalls on the wiki. The clone
 * is cached per organization and refreshed only when the wiki head moved.
 */
export async function prepareContextWiki(options: {
  apiHost: string;
  projectId: number;
  authenticatedFetch: AuthenticatedFetch;
  cacheDir: string;
  log: AgentScopedLogger;
}): Promise<ContextWikiMount | null> {
  // Resolve the organization before locking: every destructive path below is
  // org-scoped (mountDir and its .bundle/.head siblings under cacheDir), so the
  // lock must key on the org, not the project. Two projects in one org would
  // otherwise take different keys and rm -rf then clone the same checkout at once.
  const organizationId = await resolveOrganizationId(options);
  if (!organizationId) {
    return null;
  }
  const key = `${options.apiHost.replace(/\/$/, "")}:${options.cacheDir}:${organizationId}`;
  const pending = inflight.get(key);
  if (pending) {
    return pending;
  }
  const preparation = prepare(organizationId, options).catch((err) => {
    options.log.warn("Failed to prepare the context wiki mount", {
      error: err instanceof Error ? err.message : String(err),
    });
    return null;
  });
  inflight.set(key, preparation);
  try {
    return await preparation;
  } finally {
    inflight.delete(key);
  }
}

async function resolveOrganizationId(options: {
  apiHost: string;
  projectId: number;
  authenticatedFetch: AuthenticatedFetch;
  log: AgentScopedLogger;
}): Promise<string | null> {
  const cacheKey = `${options.apiHost}:${options.projectId}`;
  const cached = organizationIds.get(cacheKey);
  if (cached) {
    return cached;
  }
  try {
    const base = options.apiHost.replace(/\/$/, "");
    const projectResponse = await options.authenticatedFetch(
      `${base}/api/projects/${options.projectId}/`,
      { signal: AbortSignal.timeout(API_TIMEOUT_MS) },
    );
    if (!projectResponse.ok) {
      return null;
    }
    const project = (await projectResponse.json()) as {
      organization?: unknown;
    };
    if (typeof project.organization !== "string" || !project.organization) {
      return null;
    }
    organizationIds.set(cacheKey, project.organization);
    return project.organization;
  } catch (err) {
    options.log.warn("Failed to resolve the context wiki organization", {
      error: err instanceof Error ? err.message : String(err),
    });
    return null;
  }
}

async function prepare(
  organizationId: string,
  options: {
    apiHost: string;
    authenticatedFetch: AuthenticatedFetch;
    cacheDir: string;
    log: AgentScopedLogger;
  },
): Promise<ContextWikiMount | null> {
  const base = options.apiHost.replace(/\/$/, "");

  // 404 = wiki not enabled, 403 = flag off or the org has private projects;
  // both simply mean "no wiki for this session".
  const exportResponse = await options.authenticatedFetch(
    `${base}/api/organizations/${organizationId}/context_layer/export/`,
    { signal: AbortSignal.timeout(API_TIMEOUT_MS) },
  );
  if (!exportResponse.ok) {
    return null;
  }
  const wikiExport = (await exportResponse.json()) as {
    url?: unknown;
    head_sha?: unknown;
  };
  const { url, head_sha: headSha } = wikiExport;
  if (typeof url !== "string" || typeof headSha !== "string") {
    return null;
  }

  // One directory per head, created by an atomic rename: existence means the
  // clone completed, sessions on an older head keep their checkout across a
  // head move, and a failed refresh never destroys a working mount.
  const orgDir = path.join(options.cacheDir, organizationId);
  const mountDir = path.join(orgDir, headSha);
  const commitsPath = `/api/organizations/${organizationId}/context_layer/commits/`;
  if (fs.existsSync(mountDir)) {
    return { path: mountDir, commitsPath };
  }

  // The bundle URL is presigned, so this fetch is deliberately unauthenticated.
  const bundleResponse = await fetch(url, {
    signal: AbortSignal.timeout(BUNDLE_DOWNLOAD_TIMEOUT_MS),
  });
  if (!bundleResponse.ok || !bundleResponse.body) {
    return null;
  }
  await fs.promises.mkdir(orgDir, { recursive: true });
  const bundlePath = path.join(orgDir, `.bundle-${headSha}`);
  const stagingDir = path.join(orgDir, `.staging-${headSha}`);
  try {
    await pipeline(
      Readable.fromWeb(bundleResponse.body as unknown as WebReadableStream),
      boundedBytes(MAX_BUNDLE_BYTES),
      fs.createWriteStream(bundlePath),
    );
    await runGit(["clone", "--quiet", bundlePath, stagingDir]);
    await runGit(["-C", stagingDir, "checkout", "--quiet", "main"]);
    try {
      await fs.promises.rename(stagingDir, mountDir);
    } catch {
      // A concurrent preparation on another key won the rename; theirs is
      // complete, so use it.
      if (!fs.existsSync(mountDir)) {
        throw new Error("could not move the wiki checkout into place");
      }
    }
  } finally {
    await fs.promises.rm(bundlePath, { force: true });
    await fs.promises.rm(stagingDir, { recursive: true, force: true });
  }
  await pruneStaleCheckouts(orgDir, headSha);
  options.log.info("Mounted the context wiki", { headSha });
  return { path: mountDir, commitsPath };
}

function boundedBytes(limit: number): Transform {
  let seen = 0;
  return new Transform({
    transform(chunk: Buffer, _encoding, callback) {
      seen += chunk.length;
      if (seen > limit) {
        callback(new Error(`wiki bundle exceeds ${limit} bytes`));
        return;
      }
      callback(null, chunk);
    },
  });
}

async function pruneStaleCheckouts(
  orgDir: string,
  currentHeadSha: string,
): Promise<void> {
  try {
    for (const entry of await fs.promises.readdir(orgDir)) {
      if (entry === currentHeadSha) {
        continue;
      }
      const entryPath = path.join(orgDir, entry);
      const age = Date.now() - (await fs.promises.stat(entryPath)).mtimeMs;
      if (age > STALE_CHECKOUT_MS) {
        await fs.promises.rm(entryPath, { recursive: true, force: true });
      }
    }
  } catch {
    // Best-effort: a prune failure never fails a mount.
  }
}

async function runGit(args: string[]): Promise<void> {
  const result = await execGit(args, { timeoutMs: GIT_TIMEOUT_MS });
  if (result.exitCode !== 0) {
    throw new Error(
      `git ${args[0]} failed: ${result.error ?? result.stderr.trim()}`,
    );
  }
}
