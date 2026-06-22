// vitest globalSetup for the default (unit + workers) suite.
//
// `src/hono/dispatcher.ts` and `tests/unit/exec.test.ts` import
// `@shared/guidelines.md`, which the `@shared/*` tsconfig alias maps to
// `shared/guidelines.md`. That file is gitignored and produced by
// `scripts/copy-instructions.ts`, so we materialize it once before the suite runs —
// otherwise the import fails to resolve on a fresh checkout or in any CI job that
// doesn't run a separate pre-build step first.

import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

const MCP_DIR = resolve(__dirname, '..')

// Spawned (rather than imported and called) because copy-instructions.ts relies on
// CommonJS globals (`__dirname`, `require.main`) that aren't reliably present in
// vitest's ESM module runner; running it through tsx keeps it in its native context.
export function copySharedInstructions(): void {
    const result = spawnSync('pnpm', ['exec', 'tsx', 'scripts/copy-instructions.ts'], {
        cwd: MCP_DIR,
        stdio: 'inherit',
        env: process.env,
    })
    if (result.status !== 0) {
        throw new Error(`copy-instructions failed (exit code ${result.status})`)
    }
}

export async function setup(): Promise<void> {
    copySharedInstructions()
}
