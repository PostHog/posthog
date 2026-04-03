/**
 * Read .snapshots.yml baseline files.
 *
 * Schema (v1, signed):
 *   version: 1
 *   config:
 *     api: https://app.posthog.com
 *     team: "12345"
 *     repo: "5b6c3630-3e94-4cd0-a1c7-81c34d40a30c"
 *   snapshots:
 *     button--primary:
 *       hash: "v1.k1.3f2a...9c10.2S8h...Q"
 *
 * The hash value is an HMAC-signed token: v1.<kid>.<blake3hex>.<mac_b64url>
 * Produced exclusively by the backend on approval.
 */
import { existsSync, readFileSync } from 'node:fs'
import { parse } from 'yaml'

export interface SnapshotConfig {
    api: string
    team: string
    repo: string
}

export interface SnapshotsFile {
    version: number
    config?: SnapshotConfig
    snapshots: Record<string, { hash: string }>
}

/**
 * Read snapshots.yml and return the parsed file.
 * Returns null if the file doesn't exist or is invalid.
 */
export function readSnapshotsFile(path: string): SnapshotsFile | null {
    if (!existsSync(path)) {
        return null
    }

    const content = readFileSync(path, 'utf-8')
    const data = parse(content) as SnapshotsFile | null

    if (!data || data.version !== 1) {
        return null
    }

    return data
}

/**
 * Read snapshots.yml and return identifier → signed hash map.
 * Returns empty map if file doesn't exist or is invalid.
 */
export function readBaselineHashes(path: string): Record<string, string> {
    const file = readSnapshotsFile(path)
    if (!file) {
        return {}
    }

    const hashes: Record<string, string> = {}
    for (const [identifier, entry] of Object.entries(file.snapshots ?? {})) {
        if (entry && typeof entry.hash === 'string') {
            hashes[identifier] = entry.hash
        }
    }
    return hashes
}
