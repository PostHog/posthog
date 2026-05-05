// Dev runner for the Hono MCP server. esbuild rebuilds on file change and
// respawns the Node process so the dev loop matches the production bundle:
//   - the same `cloudflare:workers` shim plugin (no `tsx` divergence)
//   - the same `.html`/`.md` text loaders (template imports just work)
//   - the same single-mjs output that ships in production
//
// Trade-off vs `tsx --watch`: an extra ~1–2s per change for the bundle step,
// but zero behaviour drift — what runs locally is what runs in the container.
import { context } from 'esbuild'
import { resolve } from 'path'
import { existsSync } from 'fs'
import { spawn, type ChildProcess } from 'child_process'

// Load `.env` (gitignored) before spawning so the child Node process inherits
// the dev config (PostHog base URLs, ports, etc.). Wrangler's `.dev.vars` is
// CF-runtime-specific; the Hono dev server reads the same env via `process.env`.
if (existsSync(resolve(process.cwd(), '.env'))) {
    process.loadEnvFile(resolve(process.cwd(), '.env'))
}

// Bridge flox's `SSL_CERT_FILE` (used by Node-the-CLI as a CA bundle) to
// `NODE_EXTRA_CA_CERTS` (read by Node's TLS layer at startup). Without it, the
// child process can't reach `https://us.posthog.com` from inside flox. `.env`
// wins if the user set NODE_EXTRA_CA_CERTS explicitly.
if (!process.env.NODE_EXTRA_CA_CERTS && process.env.SSL_CERT_FILE) {
    process.env.NODE_EXTRA_CA_CERTS = process.env.SSL_CERT_FILE
}

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

let child: ChildProcess | undefined
const launch = (): void => {
    if (child) {
        child.removeAllListeners()
        child.kill('SIGTERM')
    }
    child = spawn(process.execPath, [outfile], {
        stdio: 'inherit',
        env: process.env,
    })
    child.on('exit', (code, signal) => {
        if (signal === 'SIGTERM') {
            return
        }
        if (code !== 0) {
            console.warn(`[dev-hono] node exited with code=${code}; waiting for next rebuild...`)
        }
    })
}

const restartPlugin = {
    name: 'dev-hono-restart',
    setup(build: any): void {
        build.onEnd((result: { errors: unknown[] }) => {
            if (result.errors.length > 0) {
                console.error(`[dev-hono] build failed with ${result.errors.length} error(s); not restarting`)
                return
            }
            launch()
        })
    },
}

async function main(): Promise<void> {
    const ctx = await context({
        entryPoints: [resolve(process.cwd(), 'src/hono/index.ts')],
        bundle: true,
        platform: 'node',
        target: 'node22',
        format: 'esm',
        outfile,
        sourcemap: true,
        external: [],
        plugins: [uiAppsStubPlugin, cloudflareWorkersShim, restartPlugin],
        loader: {
            '.html': 'text',
            '.md': 'text',
            '.json': 'json',
        },
        define: {
            'process.env.NODE_ENV': '"development"',
        },
        banner: {
            js: `import { createRequire as __cr } from 'module'; const require = __cr(import.meta.url);`,
        },
        logLevel: 'info',
    })

    const shutdown = async (): Promise<void> => {
        if (child) {
            child.kill('SIGTERM')
        }
        await ctx.dispose()
        process.exit(0)
    }
    process.on('SIGINT', shutdown)
    process.on('SIGTERM', shutdown)

    await ctx.watch()
    console.info('[dev-hono] watching src/hono/** for changes')
}

main().catch((err: unknown) => {
    console.error('[dev-hono] fatal:', err)
    process.exit(1)
})
