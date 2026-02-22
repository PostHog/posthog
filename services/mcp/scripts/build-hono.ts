import { build } from 'esbuild'
import { resolve } from 'path'

const outfile = resolve(process.cwd(), 'dist/hono-server.mjs')

build({
    entryPoints: [resolve(process.cwd(), 'src/hono/index.ts')],
    bundle: true,
    platform: 'node',
    target: 'node22',
    format: 'esm',
    outfile,
    sourcemap: true,
    external: ['ioredis'],
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
        console.log(`Built Hono MCP server → ${outfile}`)
    })
    .catch((err) => {
        console.error('Build failed:', err)
        process.exit(1)
    })
