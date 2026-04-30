import { build } from 'esbuild'
import { resolve } from 'path'
import { existsSync } from 'fs'

const outfile = resolve(process.cwd(), 'dist/hono-server.mjs')

const uiAppsStubPlugin = {
    name: 'ui-apps-stub',
    setup(build: any): void {
        build.onResolve({ filter: /ui-apps-dist\/.*\.html$/ }, (args: any) => {
            const fullPath = resolve(args.resolveDir, args.path)
            if (!existsSync(fullPath)) {
                return { path: args.path, namespace: 'ui-apps-stub' }
            }
            return undefined
        })
        build.onLoad({ filter: /.*/, namespace: 'ui-apps-stub' }, () => ({
            contents: 'export default ""',
            loader: 'js' as const,
        }))
    },
}

const cloudflareWorkersShim = {
    name: 'cloudflare-workers-shim',
    setup(build: any): void {
        build.onResolve({ filter: /^cloudflare:workers$/ }, () => ({
            path: 'cloudflare:workers',
            namespace: 'cf-shim',
        }))
        build.onLoad({ filter: /.*/, namespace: 'cf-shim' }, () => ({
            contents: `export const env = new Proxy({}, { get: (_, key) => process.env[key] })`,
            loader: 'js' as const,
        }))
    },
}

build({
    entryPoints: [resolve(process.cwd(), 'src/hono/index.ts')],
    bundle: true,
    platform: 'node',
    target: 'node22',
    format: 'esm',
    outfile,
    sourcemap: true,
    // No externals: ioredis and every other prod dep is pure-JS (or has Node-target
    // shims that esbuild handles). Bundling everything lets the runtime image ship
    // a single .mjs with no node_modules at all.
    external: [],
    plugins: [uiAppsStubPlugin, cloudflareWorkersShim],
    loader: {
        '.html': 'text',
        '.md': 'text',
        '.json': 'json',
    },
    define: {
        'process.env.NODE_ENV': '"production"',
    },
    // Bundled CJS modules (e.g. ioredis using `require('util')` at runtime) call
    // through to a global `require`. ESM modules don't have one, so we inject one
    // via a banner. We import `createRequire` under an alias so the bundler's own
    // CJS-interop shim (which also references `createRequire`) doesn't collide.
    banner: {
        js: `import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);`,
    },
})
    .then(() => {
        console.info(`Built MCP server → ${outfile}`)
    })
    .catch((err: unknown) => {
        console.error('Build failed:', err)
        process.exit(1)
    })
