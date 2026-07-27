import type { BuildOptions, Plugin } from 'esbuild'
// Shared esbuild config for the Hono runtime. `build-hono.ts` runs it once for
// production; `dev-hono.ts` wraps it in `context().watch()` for the dev loop.
//
// No externals: ioredis and every other prod dep is pure-JS (or has a Node-target
// shim esbuild handles). Bundling everything lets the runtime image ship a single
// .mjs with no node_modules at all.
import { resolve } from 'path'

export const honoOutfile = resolve(process.cwd(), 'dist/hono-server.mjs')
export const cliOutfile = resolve(process.cwd(), 'dist/posthog-api-cli.mjs')

type HonoEsbuildOptions = {
    dev?: boolean
    extraPlugins?: Plugin[]
    outfile?: string
    sourcemap?: boolean
}

const cfWorkersStub: Plugin = {
    name: 'cf-workers-stub',
    setup(build): void {
        build.onResolve({ filter: /^cloudflare:workers$/ }, () => ({
            path: 'cloudflare:workers',
            namespace: 'cf-stub',
        }))
        build.onLoad({ filter: /.*/, namespace: 'cf-stub' }, () => ({
            contents: 'export const env = undefined',
            loader: 'js',
        }))
    },
}

export function honoEsbuildOptions(opts: HonoEsbuildOptions = {}): BuildOptions {
    return {
        entryPoints: [resolve(process.cwd(), 'src/hono/index.ts')],
        bundle: true,
        platform: 'node',
        target: 'node22',
        format: 'esm',
        outfile: opts.outfile ?? honoOutfile,
        sourcemap: opts.sourcemap ?? true,
        external: [],
        plugins: [cfWorkersStub, ...(opts.extraPlugins ?? [])],
        loader: { '.html': 'text', '.md': 'text', '.json': 'json' },
        define: { 'process.env.NODE_ENV': opts.dev ? '"development"' : '"production"' },
        // Bundled CJS modules (e.g. ioredis using `require('util')`) call through
        // to a global `require`. ESM has no `require`; banner injects one. The
        // alias avoids colliding with esbuild's own CJS-interop shim.
        banner: { js: `import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);` },
    }
}

export function cliEsbuildOptions(opts: HonoEsbuildOptions = {}): BuildOptions {
    return {
        ...honoEsbuildOptions(opts),
        entryPoints: [resolve(process.cwd(), 'src/cli/index.ts')],
        outfile: opts.outfile ?? cliOutfile,
    }
}
