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

build({
    entryPoints: [resolve(process.cwd(), 'src/hono/index.ts')],
    bundle: true,
    platform: 'node',
    target: 'node22',
    format: 'esm',
    outfile,
    sourcemap: true,
    external: ['ioredis'],
    plugins: [uiAppsStubPlugin],
    loader: {
        '.html': 'text',
        '.md': 'text',
        '.json': 'json',
    },
    define: {
        'process.env.NODE_ENV': '"production"',
    },
    banner: {
        js: `import { createRequire } from 'module'; const require = createRequire(import.meta.url);`,
    },
})
    .then(() => {
        console.info(`Built Hono MCP server → ${outfile}`)
    })
    .catch((err: unknown) => {
        console.error('Build failed:', err)
        process.exit(1)
    })
