/**
 * Directory scanner for PNG screenshots.
 *
 * Finds all PNGs in a directory and derives snapshot IDs from filenames.
 * Contract: filename == snapshot ID (without extension)
 */
import { existsSync, readdirSync, statSync } from 'node:fs'
import { basename, extname, join } from 'node:path'

export interface ScannedSnapshot {
    identifier: string
    filePath: string
}

/**
 * Recursively scan directory for PNG files.
 * Derives snapshot ID from filename: `button--primary.png` → `button--primary`
 *
 * Returns an empty array if the directory does not exist — callers decide
 * whether that is an error (verify/submit) or a no-op (run upload, which can
 * fire even when a prior test step produced no screenshots).
 */
export function scanDirectory(dir: string): ScannedSnapshot[] {
    if (!existsSync(dir)) {
        return []
    }

    const snapshots: ScannedSnapshot[] = []

    function scan(currentDir: string): void {
        const entries = readdirSync(currentDir)

        for (const entry of entries) {
            const fullPath = join(currentDir, entry)
            const stat = statSync(fullPath)

            if (stat.isDirectory()) {
                scan(fullPath)
            } else if (stat.isFile() && extname(entry).toLowerCase() === '.png') {
                const identifier = deriveIdentifier(entry)
                snapshots.push({
                    identifier,
                    filePath: fullPath,
                })
            }
        }
    }

    scan(dir)

    // Sort by identifier for deterministic output
    snapshots.sort((a, b) => a.identifier.localeCompare(b.identifier))

    return snapshots
}

/**
 * Derive snapshot identifier from filename.
 * Strips extension and sanitizes for use as ID.
 */
function deriveIdentifier(filename: string): string {
    // Remove extension
    const name = basename(filename, extname(filename))

    // Basic sanitization - keep alphanumeric, dashes, underscores
    // Replace other chars with dashes
    return name.replace(/[^a-zA-Z0-9_-]/g, '-')
}
