/**
 * Loads `shared/guidelines.md` for the InstructionsBuilder.
 *
 * Two-stage lookup keeps dev/test and production bundle behavior aligned:
 *   1. Try the `@shared/guidelines.md` esbuild alias — works in the
 *      production bundle.
 *   2. Fall back to reading from disk relative to cwd — works in Vitest /
 *      stdio dev / any plain Node runtime.
 *
 * Extracted from the legacy dispatcher so both protocol pipelines share it.
 */

export function loadGuidelines(): string {
    try {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const mod = require('@shared/guidelines.md')
        return typeof mod === 'string' ? mod : (mod?.default ?? '')
    } catch {
        // @shared alias only resolves in the esbuild production bundle.
    }
    try {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const fs = require('node:fs')
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const path = require('node:path')
        return fs.readFileSync(path.resolve(process.cwd(), 'shared/guidelines.md'), 'utf-8')
    } catch {
        return ''
    }
}
