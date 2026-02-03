/**
 * Read .snapshots.yml baseline files.
 *
 * Schema:
 *   version: 1
 *   snapshots:
 *     Button--primary: abc123...
 *     LoginPage: def456...
 */
import { existsSync, readFileSync } from 'node:fs'
import { parse } from 'yaml'

interface SnapshotsFile {
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
