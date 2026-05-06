// esbuild watch + node respawn — same bundling pipeline as build-hono.ts so
// dev and prod behave identically. tsx isn't used directly because it can't
// load the `.md` template imports or stub the `cloudflare:workers` builtin.
import { context } from 'esbuild'
import { resolve } from 'path'
import { existsSync } from 'fs'
import { spawn, type ChildProcess } from 'child_process'

if (existsSync(resolve(process.cwd(), '.env'))) {
    process.loadEnvFile(resolve(process.cwd(), '.env'))
}

// flox sets SSL_CERT_FILE; Node's TLS layer only reads NODE_EXTRA_CA_CERTS.
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
