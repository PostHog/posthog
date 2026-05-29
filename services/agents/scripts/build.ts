/**
 * Bundles the four agent-platform entrypoints into self-contained ESM
 * files under `dist/`. Mirrors services/mcp/scripts/build-hono.ts in shape
 * (single esbuild invocation, no externals, banner that shims `require`
 * for CJS deps like `pg` and `node-pg-migrate`).
 *
 * Output layout (consumed by services/agents/Dockerfile):
 *   dist/ingress.mjs
 *   dist/runner.mjs
 *   dist/janitor.mjs
 *   dist/migrate.mjs
 *
 * `migrate.mjs` reads SQL files at runtime from `../migrations/` relative
 * to the bundle (see @posthog/agent-migrations lib.ts). The Dockerfile
 * copies the SQL files to `/code/migrations/` so that path resolves.
 */

import { build } from 'esbuild'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(HERE, '../../..')
const OUT_DIR = resolve(HERE, '..', 'dist')

const ENTRY_POINTS = {
    ingress: resolve(ROOT, 'services/agent-ingress/src/index.ts'),
    runner: resolve(ROOT, 'services/agent-runner/src/index.ts'),
    janitor: resolve(ROOT, 'services/agent-janitor/src/index.ts'),
    migrate: resolve(ROOT, 'services/agent-migrations/src/bin.ts'),
}

await build({
    entryPoints: ENTRY_POINTS,
    bundle: true,
    platform: 'node',
    target: 'node24',
    format: 'esm',
    outdir: OUT_DIR,
    outExtension: { '.js': '.mjs' },
    sourcemap: true,
    // - `pg-native`: optional C addon, only loaded via `require('pg').native` which no service uses.
    //   Leave unresolved at bundle time to avoid dragging libpq into the runtime image.
    // - `node-rdkafka`: native binding (.node); cannot be inlined into a .mjs bundle. The runtime
    //   image ships its node_modules so `await import('node-rdkafka')` resolves at boot.
    external: ['pg-native', 'node-rdkafka'],
    loader: { '.json': 'json', '.sql': 'text' },
    define: { 'process.env.NODE_ENV': '"production"' },
    // CJS deps (pg, node-pg-migrate, jose) call through to a global
    // `require`. ESM has no `require`; banner injects one. Same pattern
    // as services/mcp/scripts/hono-esbuild-config.ts.
    banner: { js: `import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);` },
    logLevel: 'info',
})

for (const name of Object.keys(ENTRY_POINTS)) {
    console.info(`built dist/${name}.mjs`)
}
