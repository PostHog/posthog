/**
 * Read/write .snapshots.yml baseline files.
 *
 * Schema:
 *   version: 1
 *   snapshots:
 *     Button--primary: abc123...
 *     LoginPage: def456...
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { parse, stringify } from 'yaml'

export interface SnapshotsFile {
    version: number
    snapshots: Record<string, string>
}

/**
 * Read snapshots.yml and return identifier → hash map.
 * Returns empty map if file doesn't exist.
 */
export function readSnapshots(path: string): Record<string, string> {
    if (!existsSync(path)) {
        return {}
    }

    const content = readFileSync(path, 'utf-8')
    const data = parse(content) as SnapshotsFile | null

    if (!data || data.version !== 1) {
        return {}
    }

    return data.snapshots ?? {}
}

/**
 * Write snapshots.yml with sorted keys for deterministic output.
 */
export function writeSnapshots(path: string, snapshots: Record<string, string>): void {
    const sortedSnapshots: Record<string, string> = {}
    for (const key of Object.keys(snapshots).sort()) {
        sortedSnapshots[key] = snapshots[key]
    }

    const data: SnapshotsFile = {
        version: 1,
        snapshots: sortedSnapshots,
    }

    const content = stringify(data, {
        lineWidth: 0, // Don't wrap lines
        sortMapEntries: true,
    })

    writeFileSync(path, content, 'utf-8')
}

/**
 * Merge new hashes into existing snapshots.
 * Used when approving changes.
 */
export function mergeSnapshots(
    existing: Record<string, string>,
    updates: Array<{ identifier: string; hash: string }>
): Record<string, string> {
    const merged = { ...existing }
    for (const { identifier, hash } of updates) {
        merged[identifier] = hash
    }
    return merged
}
