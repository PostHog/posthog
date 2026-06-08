// vitest globalSetup hook for the integration suite.
//
// MCP UI apps are React bundles emitted to `public/ui-apps/<app>/{main.js,styles.css}`
// by `scripts/build-ui-apps.ts`. They need to exist on disk before the integration
// suite runs, because both runtimes (Hono via `serveStatic`, CF via Workers Static
// Assets) serve them from `./public/`. We build them once per test session and
// skip if the output is already present (much faster on repeat runs).

import { spawnSync } from 'node:child_process'
import { existsSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'

import { copyInstructions } from '../../scripts/copy-instructions'

const MCP_DIR = resolve(__dirname, '..', '..')
const UI_APPS_DIR = resolve(MCP_DIR, 'public', 'ui-apps')

function uiAppsAlreadyBuilt(): boolean {
    if (!existsSync(UI_APPS_DIR)) {
        return false
    }
    return readdirSync(UI_APPS_DIR).some((name) => existsSync(resolve(UI_APPS_DIR, name, 'main.js')))
}

export async function setup(): Promise<void> {
    // Populate `shared/guidelines.md` (gitignored) so the `@shared/*` alias used by
    // `src/hono/dispatcher.ts` and `src/mcp.ts` resolves. The integration CI job
    // doesn't run the standalone copy step the unit job does, and it's absent on a
    // fresh local checkout too — generate it here so the suite is self-sufficient.
    copyInstructions()

    if (uiAppsAlreadyBuilt()) {
        return
    }
    console.info('[integration setup] Building MCP UI apps (one-time)…')
    const result = spawnSync('pnpm', ['run', 'build:ui-apps'], {
        cwd: MCP_DIR,
        stdio: 'inherit',
        env: process.env,
    })
    if (result.status !== 0) {
        throw new Error(`build:ui-apps failed (exit code ${result.status})`)
    }
}
