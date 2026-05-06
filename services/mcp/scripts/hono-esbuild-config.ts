// Shared esbuild config for the Hono runtime. `build-hono.ts` runs it once for
// production; `dev-hono.ts` wraps it in `context().watch()` for the dev loop.
//
// No externals: ioredis and every other prod dep is pure-JS (or has a Node-target
// shim esbuild handles). Bundling everything lets the runtime image ship a single
// .mjs with no node_modules at all.
import { existsSync } from 'fs'
import { resolve } from 'path'
import type { BuildOptions, Plugin } from 'esbuild'

export const honoOutfile = resolve(process.cwd(), 'dist/hono-server.mjs')

// Stub out unbuilt MCP UI app HTML imports. The build target may run before the
// UI app pipeline; in that case the import resolves to an empty default export.
const uiAppsStubPlugin: Plugin = {
    name: 'ui-apps-stub',
    setup(build): void {
        build.onResolve({ filter: /ui-apps-dist\/.*\.html$/ }, (args) => {
            const fullPath = resolve(args.resolveDir, args.path)
            if (!existsSync(fullPath)) {
                return { path: args.path, namespace: 'ui-apps-stub' }
            }
            return undefined
        })
        build.onLoad({ filter: /.*/, namespace: 'ui-apps-stub' }, () => ({
            contents: 'export default ""',
            loader: 'js',
        }))
    },
}

// `cloudflare:workers` is a CF runtime builtin. Replace with a Proxy over
// `process.env` so the same source compiles for Node.
const cloudflareWorkersShim: Plugin = {
    name: 'cloudflare-workers-shim',
    setup(build): void {
        build.onResolve({ filter: /^cloudflare:workers$/ }, () => ({
            path: 'cloudflare:workers',
            namespace: 'cf-shim',
        }))
        build.onLoad({ filter: /.*/, namespace: 'cf-shim' }, () => ({
            contents: `export const env = new Proxy({}, { get: (_, key) => process.env[key] })`,
            loader: 'js',
        }))
    },
}

export function honoEsbuildOptions(opts: { dev?: boolean; extraPlugins?: Plugin[] } = {}): BuildOptions {
    return {
        entryPoints: [resolve(process.cwd(), 'src/hono/index.ts')],
        bundle: true,
        platform: 'node',
        target: 'node22',
        format: 'esm',
        outfile: honoOutfile,
        sourcemap: true,
        external: [],
        plugins: [uiAppsStubPlugin, cloudflareWorkersShim, ...(opts.extraPlugins ?? [])],
        loader: { '.html': 'text', '.md': 'text', '.json': 'json' },
        define: { 'process.env.NODE_ENV': opts.dev ? '"development"' : '"production"' },
        // Bundled CJS modules (e.g. ioredis using `require('util')`) call through
        // to a global `require`. ESM has no `require`; banner injects one. The
        // alias avoids colliding with esbuild's own CJS-interop shim.
        banner: { js: `import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);` },
    }
}
