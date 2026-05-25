/**
 * Cloudflare-KV–backed cache for context-mill resources.
 *
 * Each DO previously fetched and held the full 2.7 MiB bundle zip in its own
 * heap to serve `resources/list` and `resources/read`. Most of that data was
 * never read by any client in a typical session. This module replaces that
 * with two lazy lookups against `env.MCP_KV`:
 *
 *   - `getManifest(env)`     — small JSON catalog (~30 KiB), TTL 1h. Used at
 *     DO init to register the resource list. Refreshes after a context-mill
 *     release within an hour.
 *
 *   - `getResourceText(env, entry)` — per-resource text (URL-shaped entries
 *     are followed to their `downloadUrl` and decompressed if zipped). TTL 8h.
 *     Only fetched when a client actually issues `resources/read`.
 *
 * Both helpers fall back to an origin fetch when the KV binding is absent
 * (some test harnesses don't bind it). Writes are fire-and-forget via
 * `Promise.resolve()` so KV latency never blocks the request path.
 */
import { strFromU8, unzipSync } from 'fflate'

import { loadContextMillManifest } from './manifest-loader'
import type { ContextMillManifest, ContextMillResource } from './manifest-types'

// The context-mill release publishes only a bundle zip (not a standalone
// manifest.json). We fetch that zip, extract just `manifest.json`, and discard
// the rest — keeping ~30 KiB of parsed JSON in heap rather than the ~2.7 MiB
// of zipped resource bytes. Per-resource content is fetched separately on demand
// via each entry's `downloadUrl`, which DOES exist as a standalone release asset.
const CONTEXT_MILL_BUNDLE_URL =
    'https://github.com/PostHog/context-mill/releases/latest/download/skills-mcp-resources.zip'
const MANIFEST_FILE_IN_BUNDLE = 'manifest.json'

const MANIFEST_KV_KEY = 'ctx-mill:manifest:latest'
const MANIFEST_TTL_SECONDS = 60 * 60 // 1h: a new release propagates within an hour.

const RESOURCE_TTL_SECONDS = 8 * 60 * 60 // 8h: content is version-keyed and effectively immutable.

interface KVLike {
    get(key: string, type?: 'text'): Promise<string | null>
    put(key: string, value: string, options?: { expirationTtl?: number }): Promise<void>
}

function resourceKey(version: string, entryId: string): string {
    return `ctx-mill:resource:${version}:${entryId}`
}

function isLikelyUrl(text: string): boolean {
    return text.startsWith('http://') || text.startsWith('https://')
}

async function fetchManifestFromOrigin(localUrl?: string): Promise<ContextMillManifest> {
    if (localUrl) {
        // Local-dev: serve a raw manifest.json from a directory the dev controls.
        const url = `${localUrl.replace(/\/$/, '')}/manifest.json`
        const response = await fetch(url, { cache: 'no-store' })
        if (!response.ok) {
            throw new Error(`context-mill manifest fetch failed: ${response.status} ${url}`)
        }
        return loadContextMillManifest(await response.json())
    }
    const response = await fetch(CONTEXT_MILL_BUNDLE_URL)
    if (!response.ok) {
        throw new Error(`context-mill bundle fetch failed: ${response.status} ${CONTEXT_MILL_BUNDLE_URL}`)
    }
    const bytes = new Uint8Array(await response.arrayBuffer())
    const unzipped = unzipSync(bytes)
    const manifestBytes = unzipped[MANIFEST_FILE_IN_BUNDLE]
    if (!manifestBytes) {
        throw new Error(`context-mill bundle is missing ${MANIFEST_FILE_IN_BUNDLE}`)
    }
    // `bytes` (the full zip) goes out of scope here; only the parsed manifest
    // survives in the returned object. This is the whole point — we never
    // retain the bundle in DO heap.
    return loadContextMillManifest(JSON.parse(strFromU8(manifestBytes)))
}

export async function getManifest(
    env: { MCP_KV: KVNamespace | undefined },
    localUrl?: string
): Promise<ContextMillManifest> {
    // Local-dev override always bypasses KV — devs expect immediate visibility
    // when they swap the underlying skills bundle.
    if (localUrl) {
        return fetchManifestFromOrigin(localUrl)
    }
    const kv = env.MCP_KV as KVLike | undefined
    if (kv) {
        const cached = await kv.get(MANIFEST_KV_KEY, 'text')
        if (cached) {
            try {
                return loadContextMillManifest(JSON.parse(cached))
            } catch {
                // Corrupted cache entry — fall through to origin fetch and overwrite.
            }
        }
    }
    const fresh = await fetchManifestFromOrigin()
    if (kv) {
        // Don't await — the request that triggered this lookup shouldn't pay KV
        // write latency. KV writes are idempotent so retries on next miss are fine.
        void kv.put(MANIFEST_KV_KEY, JSON.stringify(fresh), { expirationTtl: MANIFEST_TTL_SECONDS }).catch(() => {
            /* swallow — we already have the value to return */
        })
    }
    return fresh
}

async function fetchResourceTextFromOrigin(downloadUrl: string, mimeType: string): Promise<string> {
    const response = await fetch(downloadUrl)
    if (!response.ok) {
        throw new Error(`context-mill resource fetch failed: ${response.status} ${downloadUrl}`)
    }
    const bytes = new Uint8Array(await response.arrayBuffer())
    // Inner files are themselves zips for most resources. Detect by mimeType
    // or by the local-file-header magic (PK\x03\x04 → 0x50 0x4B 0x03 0x04).
    const looksLikeZip =
        mimeType === 'application/zip' ||
        (bytes.length >= 4 && bytes[0] === 0x50 && bytes[1] === 0x4b && bytes[2] === 0x03 && bytes[3] === 0x04)
    if (!looksLikeZip) {
        return strFromU8(bytes)
    }
    const inner = unzipSync(bytes)
    // context-mill packs a single document per inner zip. Concatenate any
    // accidental multi-file zips with a separator rather than dropping data.
    const parts: string[] = []
    for (const [name, data] of Object.entries(inner)) {
        if (!data) {
            continue
        }
        parts.push(`--- ${name} ---\n${strFromU8(data)}`)
    }
    return parts.length === 1 && parts[0] ? parts[0].replace(/^--- [^\n]+ ---\n/, '') : parts.join('\n\n')
}

/**
 * Resolve the text content for a context-mill resource. When the manifest
 * already inlines the text (small content) we return it immediately. When the
 * inlined text is actually a URL (context-mill's pattern for large content)
 * we fetch the underlying file, decompress it if it's a zip, and cache the
 * decoded text in KV under a version-pinned key.
 *
 * `version` should be the manifest's `version` field — content is immutable
 * per release, so version-pinned keys never need invalidation.
 */
export async function getResourceText(
    env: { MCP_KV: KVNamespace | undefined },
    version: string,
    entry: ContextMillResource
): Promise<string> {
    const inline = entry.resource.text
    if (inline && !isLikelyUrl(inline)) {
        return inline
    }
    // The download URL is either the inline `text` (when it's a URL) or the
    // explicit `downloadUrl` field context-mill provides. Manifests we've seen
    // carry `downloadUrl` even when text is also a URL; prefer it.
    const downloadUrl =
        (typeof entry.downloadUrl === 'string' ? entry.downloadUrl : undefined) ??
        (inline && isLikelyUrl(inline) ? inline : undefined)
    if (!downloadUrl) {
        // No fetchable source — return whatever we have so the client gets a
        // well-formed response rather than an error.
        return inline ?? ''
    }
    const kv = env.MCP_KV as KVLike | undefined
    const key = resourceKey(version, entry.id)
    if (kv) {
        const cached = await kv.get(key, 'text')
        if (cached !== null) {
            return cached
        }
    }
    const fresh = await fetchResourceTextFromOrigin(downloadUrl, entry.resource.mimeType)
    if (kv) {
        void kv.put(key, fresh, { expirationTtl: RESOURCE_TTL_SECONDS }).catch(() => {
            /* swallow — we already have the value to return */
        })
    }
    return fresh
}
