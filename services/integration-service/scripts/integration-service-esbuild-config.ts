import type { BuildOptions, Plugin } from 'esbuild'
// Shared esbuild config for the integration-service Hono runtime.
// `build-integration-service.ts` runs it once for production;
// `dev-integration-service.ts` wraps it in `context().watch()` for the dev loop.
//
// No externals: every prod dep is pure-JS (or has a Node-target shim esbuild
// handles). Bundling everything lets the runtime image ship a single .mjs with no
// node_modules at all, which is what keeps this service's dependency surface
// auditable — see check-import-boundary.ts and check-deps-allowlist.ts.
import { resolve } from 'path'

export const integrationServiceOutfile = resolve(process.cwd(), 'dist/integration-service.mjs')
export const integrationServiceMetafile = resolve(process.cwd(), 'dist/meta.json')

export function integrationServiceEsbuildOptions(opts: { dev?: boolean; extraPlugins?: Plugin[] } = {}): BuildOptions {
    return {
        entryPoints: [resolve(process.cwd(), 'src/index.ts')],
        bundle: true,
        platform: 'node',
        target: 'node22',
        format: 'esm',
        outfile: integrationServiceOutfile,
        sourcemap: true,
        external: [],
        metafile: true,
        loader: { '.json': 'json' },
        define: { 'process.env.NODE_ENV': opts.dev ? '"development"' : '"production"' },
        plugins: opts.extraPlugins ?? [],
        // Bundled CJS modules (e.g. ioredis using `require('util')`) call through to a
        // global `require`. ESM has no `require`; banner injects one.
        banner: { js: `import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);` },
    }
}
