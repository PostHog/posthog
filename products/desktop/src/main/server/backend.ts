/**
 * The local backend: a loopback HTTP server that makes the desktop app work.
 *
 * It plays the role Django plays in a normal PostHog deployment, but locally:
 *  - serves the built PostHog frontend (static assets + a generated index.html),
 *    so the app shell loads with no internet connection at all
 *  - proxies backend paths (/api/, /_preflight, ...) to the configured PostHog
 *    Cloud region, attaching the personal API key as a bearer token. The token
 *    never reaches the renderer process.
 *  - keeps a small on-disk cache of bootstrap responses, served stale when the
 *    upstream is unreachable, so a signed-in app can still open offline.
 *
 * This module must stay free of Electron imports so it can be unit tested with
 * plain Node.
 */

import * as fs from 'node:fs'
import * as http from 'node:http'
import * as path from 'node:path'
import { Readable } from 'node:stream'

import { buildIndexHtml, type PreloadManifest } from './html.ts'

export interface UpstreamAuth {
    /** e.g. https://us.posthog.com (no trailing slash) */
    apiHost: string
    /** Personal API key, sent as a bearer token */
    accessToken: string
}

export interface LocalBackendOptions {
    /** Directory containing the built PostHog frontend (frontend/dist) */
    distDir: string
    /** Directory for the offline response cache */
    cacheDir: string
    /** Returns the current auth, or null when signed out. May be async when a token refresh is needed. */
    getAuth: () => UpstreamAuth | null | Promise<UpstreamAuth | null>
    /** Handles the OAuth loopback redirect (GET /oauth/callback); returns the message shown in the browser tab */
    onOAuthCallback?: (query: URLSearchParams) => Promise<{ ok: boolean; message: string }>
    /** Called when the renderer navigates to /logout */
    onSignOutRequested: () => void
    /** Called when the upstream rejects the stored credentials (e.g. a revoked API key) */
    onAuthRejected?: () => void
    /** Extra headers to send upstream, e.g. a desktop User-Agent */
    upstreamHeaders?: Record<string, string>
    /** Desktop app version, exposed to the frontend as window.__POSTHOG_DESKTOP__ */
    desktopVersion?: string
    /** Node process.platform of the main process, exposed as window.__POSTHOG_DESKTOP__.platform */
    desktopPlatform?: string
}

export interface LocalBackend {
    port: number
    origin: string
    close: () => Promise<void>
}

/**
 * Backend-owned path prefixes that must be proxied to the cloud. Everything
 * else is either a static asset (/static/) or an SPA route served index.html.
 */
const PROXY_PREFIXES = [
    '/api/',
    '/_preflight',
    '/uploaded_media/',
    '/media/',
    '/avatars/',
    '/flags',
    '/decide',
    '/array/',
    '/e/',
    '/i/',
    '/s/',
    '/site_app/',
]

/**
 * GET responses cached on disk and served when the upstream is unreachable,
 * so the app can boot offline once it has been opened online.
 */
const OFFLINE_CACHEABLE_PATHS = new Set(['/_preflight/', '/api/users/@me/', '/api/organizations/@current/'])

/** Request headers never forwarded upstream. */
const STRIPPED_REQUEST_HEADERS = new Set([
    'host',
    'connection',
    'cookie',
    'authorization',
    'origin',
    'referer',
    'accept-encoding',
    'content-length',
    'upgrade',
    'keep-alive',
    'proxy-authorization',
    'te',
    'trailer',
    'transfer-encoding',
])

/** Response headers never forwarded back to the renderer. */
const STRIPPED_RESPONSE_HEADERS = new Set([
    'content-encoding',
    'content-length',
    'transfer-encoding',
    'connection',
    'set-cookie',
    'strict-transport-security',
    'content-security-policy',
    'content-security-policy-report-only',
    'report-to',
])

const MIME_TYPES: Record<string, string> = {
    '.js': 'application/javascript',
    '.mjs': 'application/javascript',
    '.css': 'text/css',
    '.map': 'application/json',
    '.json': 'application/json',
    '.html': 'text/html; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.avif': 'image/avif',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.otf': 'font/otf',
    '.wasm': 'application/wasm',
    '.webmanifest': 'application/manifest+json',
    '.txt': 'text/plain',
    '.mp3': 'audio/mpeg',
    '.mp4': 'video/mp4',
    '.lottie': 'application/octet-stream',
}

export function isProxyPath(pathname: string): boolean {
    return PROXY_PREFIXES.some((prefix) => pathname === prefix.replace(/\/$/, '') || pathname.startsWith(prefix))
}

function cacheFileFor(cacheDir: string, pathname: string): string {
    return path.join(cacheDir, `${pathname.replace(/[^a-zA-Z0-9@._-]+/g, '_')}.json`)
}

function sendJson(res: http.ServerResponse, status: number, body: unknown): void {
    const payload = JSON.stringify(body)
    res.writeHead(status, { 'content-type': 'application/json', 'cache-control': 'no-store' })
    res.end(payload)
}

function serveStatic(distDir: string, assetPath: string, res: http.ServerResponse): void {
    const resolved = path.resolve(distDir, assetPath.replace(/^\/+/, ''))
    if (!resolved.startsWith(path.resolve(distDir) + path.sep)) {
        sendJson(res, 404, { detail: 'Not found' })
        return
    }
    let stat: fs.Stats
    try {
        stat = fs.statSync(resolved)
    } catch {
        sendJson(res, 404, { detail: 'Not found' })
        return
    }
    if (!stat.isFile()) {
        sendJson(res, 404, { detail: 'Not found' })
        return
    }
    const ext = path.extname(resolved).toLowerCase()
    // Content-hashed build outputs (e.g. index-ABC123XY.js) are safe to cache forever
    const hashed = /-[A-Z0-9]{8}\.[a-z0-9]+$/i.test(resolved)
    res.writeHead(200, {
        'content-type': MIME_TYPES[ext] || 'application/octet-stream',
        'content-length': stat.size,
        'cache-control': hashed ? 'public, max-age=31536000, immutable' : 'no-cache',
    })
    fs.createReadStream(resolved).pipe(res)
}

async function proxyRequest(
    req: http.IncomingMessage,
    res: http.ServerResponse,
    pathname: string,
    options: LocalBackendOptions
): Promise<void> {
    const auth = await options.getAuth()
    if (!auth) {
        sendJson(res, 401, {
            type: 'authentication_error',
            code: 'desktop_not_signed_in',
            detail: 'Sign in from the PostHog desktop settings window first.',
        })
        return
    }

    const method = req.method || 'GET'
    const targetUrl = auth.apiHost + (req.url || pathname)
    const headers: Record<string, string> = {}
    for (const [name, value] of Object.entries(req.headers)) {
        if (typeof value === 'string' && !STRIPPED_REQUEST_HEADERS.has(name.toLowerCase())) {
            headers[name.toLowerCase()] = value
        }
    }
    Object.assign(headers, options.upstreamHeaders)
    headers['authorization'] = `Bearer ${auth.accessToken}`

    const hasBody = method !== 'GET' && method !== 'HEAD'
    const cacheable = method === 'GET' && OFFLINE_CACHEABLE_PATHS.has(pathname)
    const cacheFile = cacheable ? cacheFileFor(options.cacheDir, pathname) : null

    let upstream: Response
    try {
        upstream = await fetch(targetUrl, {
            method,
            headers,
            body: hasBody ? (Readable.toWeb(req) as unknown as BodyInit) : undefined,
            redirect: 'manual',
            // @ts-expect-error duplex is required by undici for streaming request bodies
            duplex: hasBody ? 'half' : undefined,
        })
    } catch {
        if (cacheFile && fs.existsSync(cacheFile)) {
            try {
                const cached = JSON.parse(fs.readFileSync(cacheFile, 'utf8'))
                res.writeHead(cached.status, {
                    'content-type': cached.contentType,
                    'cache-control': 'no-store',
                    'x-posthog-desktop-cache': 'stale',
                })
                res.end(Buffer.from(cached.body, 'base64'))
                return
            } catch {
                // fall through to the offline error
            }
        }
        sendJson(res, 503, {
            type: 'server_error',
            code: 'desktop_offline',
            detail: 'PostHog Cloud is unreachable. Check your internet connection.',
        })
        return
    }

    // A rejected @me means the stored key is no longer valid (revoked or expired);
    // let the host drop back to the sign-in shell instead of a dead SPA login form
    if (pathname === '/api/users/@me/' && upstream.status === 401) {
        options.onAuthRejected?.()
    }

    const responseHeaders: Record<string, string> = {}
    upstream.headers.forEach((value, name) => {
        if (!STRIPPED_RESPONSE_HEADERS.has(name.toLowerCase())) {
            responseHeaders[name] = value
        }
    })
    const location = upstream.headers.get('location')
    if (location && location.startsWith(auth.apiHost)) {
        responseHeaders['location'] = location.slice(auth.apiHost.length) || '/'
    }
    responseHeaders['cache-control'] = 'no-store'

    if (cacheFile && upstream.status === 200) {
        const body = Buffer.from(await upstream.arrayBuffer())
        try {
            fs.mkdirSync(options.cacheDir, { recursive: true })
            fs.writeFileSync(
                cacheFile,
                JSON.stringify({
                    status: upstream.status,
                    contentType: upstream.headers.get('content-type') || 'application/json',
                    body: body.toString('base64'),
                })
            )
        } catch {
            // caching is best-effort
        }
        res.writeHead(upstream.status, responseHeaders)
        res.end(body)
        return
    }

    res.writeHead(upstream.status, responseHeaders)
    if (upstream.body) {
        Readable.fromWeb(upstream.body as import('node:stream/web').ReadableStream).pipe(res)
    } else {
        res.end()
    }
}

export function readPreloadManifest(distDir: string): PreloadManifest | null {
    try {
        return JSON.parse(fs.readFileSync(path.join(distDir, 'preload-manifest.json'), 'utf8'))
    } catch {
        return null
    }
}

export function isFrontendBuilt(distDir: string): boolean {
    return readPreloadManifest(distDir) !== null
}

const SIGNED_OUT_HTML = `<!doctype html>
<html><head><meta charset="utf-8"><title>PostHog</title></head>
<body style="font-family: sans-serif; background: #1d1f27; color: #fff; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0">
<p>Signing out...</p>
</body></html>`

function escapeHtml(text: string): string {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function oauthCallbackHtml(ok: boolean, message: string): string {
    return `<!doctype html>
<html><head><meta charset="utf-8"><title>PostHog</title></head>
<body style="font-family: sans-serif; background: #1d1f27; color: #fff; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; text-align: center">
<div><h2 style="margin-bottom: 8px">${ok ? 'Signed in to PostHog' : 'Sign-in failed'}</h2>
<p style="color: #b8b8b3">${escapeHtml(message)}</p></div>
</body></html>`
}

export async function startLocalBackend(options: LocalBackendOptions, preferredPort: number): Promise<LocalBackend> {
    const manifest = readPreloadManifest(options.distDir)
    const indexHtml = manifest
        ? buildIndexHtml(manifest, { desktopVersion: options.desktopVersion, desktopPlatform: options.desktopPlatform })
        : null

    const server = http.createServer((req, res) => {
        const url = new URL(req.url || '/', 'http://localhost')
        const pathname = url.pathname

        if (pathname === '/__desktop/health') {
            void Promise.resolve(options.getAuth()).then((auth) => {
                sendJson(res, 200, { ok: true, authenticated: auth !== null })
            })
            return
        }
        if (pathname === '/oauth/callback' && options.onOAuthCallback) {
            options
                .onOAuthCallback(url.searchParams)
                .then(({ ok, message }) => {
                    res.writeHead(ok ? 200 : 400, {
                        'content-type': 'text/html; charset=utf-8',
                        'cache-control': 'no-store',
                    })
                    res.end(oauthCallbackHtml(ok, message))
                })
                .catch(() => {
                    res.writeHead(500, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' })
                    res.end(oauthCallbackHtml(false, 'Something went wrong. Start again from the PostHog app.'))
                })
            return
        }
        if (pathname === '/logout') {
            res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' })
            res.end(SIGNED_OUT_HTML)
            options.onSignOutRequested()
            return
        }
        if (pathname.startsWith('/static/')) {
            serveStatic(options.distDir, pathname.slice('/static/'.length), res)
            return
        }
        if (isProxyPath(pathname)) {
            proxyRequest(req, res, pathname, options).catch(() => {
                if (!res.headersSent) {
                    sendJson(res, 502, { type: 'server_error', code: 'desktop_proxy_error', detail: 'Proxy error' })
                }
            })
            return
        }
        if (req.method !== 'GET' && req.method !== 'HEAD') {
            sendJson(res, 404, { detail: 'Not found' })
            return
        }
        if (!indexHtml) {
            res.writeHead(503, { 'content-type': 'text/plain; charset=utf-8' })
            res.end('The PostHog frontend is not built. Run: pnpm --filter=@posthog/frontend build')
            return
        }
        res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-cache' })
        res.end(indexHtml)
    })

    const port = await listen(server, preferredPort)
    return {
        port,
        origin: `http://127.0.0.1:${port}`,
        close: () =>
            new Promise<void>((resolve, reject) => {
                server.close((error) => (error ? reject(error) : resolve()))
                server.closeAllConnections()
            }),
    }
}

function listen(server: http.Server, preferredPort: number): Promise<number> {
    // The local origin doubles as the renderer's localStorage key, so a stable
    // port keeps the app's persisted client-side state across launches. Fall
    // back to a random free port when the preferred one is taken.
    return new Promise((resolve, reject) => {
        const tryListen = (port: number, fallback: boolean): void => {
            server.once('error', (error: NodeJS.ErrnoException) => {
                if (fallback && (error.code === 'EADDRINUSE' || error.code === 'EACCES')) {
                    tryListen(0, false)
                } else {
                    reject(error)
                }
            })
            server.listen(port, '127.0.0.1', () => {
                server.removeAllListeners('error')
                const address = server.address()
                if (address && typeof address === 'object') {
                    resolve(address.port)
                } else {
                    reject(new Error('Could not determine local backend port'))
                }
            })
        }
        tryListen(preferredPort, true)
    })
}
