import type { BuildOptions, Plugin } from 'esbuild'
// Shared esbuild config for the agent-proxy Hono runtime. `build-agent-proxy.ts`
// runs it once for production; `dev-agent-proxy.ts` wraps it in `context().watch()`
// for the dev loop.
//
// No externals: ioredis and every other prod dep is pure-JS (or has a Node-target
// shim esbuild handles). Bundling everything lets the runtime image ship a single
// .mjs with no node_modules at all.
import { resolve } from 'path'

export const agentProxyOutfile = resolve(process.cwd(), 'dist/agent-proxy-server.mjs')

export function agentProxyEsbuildOptions(opts: { dev?: boolean; extraPlugins?: Plugin[] } = {}): BuildOptions {
    return {
        entryPoints: [resolve(process.cwd(), 'src/hono/index.ts')],
        bundle: true,
        platform: 'node',
        target: 'node22',
        format: 'esm',
        outfile: agentProxyOutfile,
        sourcemap: true,
        external: [],
        loader: { '.json': 'json' },
        define: { 'process.env.NODE_ENV': opts.dev ? '"development"' : '"production"' },
        plugins: opts.extraPlugins ?? [],
        // Bundled CJS modules (e.g. ioredis using `require('util')`) call through
        // to a global `require`. ESM has no `require`; banner injects one.
        banner: { js: `import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);` },
    }
}
