#!/usr/bin/env node
/*
 * LOCAL-DEV SHIM. The PostHog Code harness (base-acp-agent.ts) GETs
 * <gateway>/v1/models and hard-requires `context_window` on every entry
 * (`model.context_window.toLocaleString()`), but the local ai-gateway's model
 * list omits it, crashing the harness at session init. The prod gateway
 * returns it; the local dev build is just behind.
 *
 * This shim transparently proxies the local gateway and injects a
 * context_window into /v1/models responses. Everything else — including the
 * streaming /v1/messages inference call — passes through untouched.
 *
 * Proper fix: have the ai-gateway return context_window. This is a stopgap to
 * run a full coding session locally.
 *
 *   node bin/gateway-model-meta-shim.js   # listens :8099, forwards :8080
 */
'use strict'

const http = require('node:http')

const UPSTREAM_HOST = process.env.SHIM_UPSTREAM_HOST || '127.0.0.1'
const UPSTREAM_PORT = parseInt(process.env.SHIM_UPSTREAM_PORT || '8080', 10)
const LISTEN_PORT = parseInt(process.env.SHIM_PORT || '8099', 10)
const DEFAULT_CONTEXT_WINDOW = parseInt(process.env.SHIM_CONTEXT_WINDOW || '200000', 10)

function rewriteModels(body) {
    const data = JSON.parse(body)
    const list = Array.isArray(data) ? data : (data.data ?? data.models ?? [])
    for (const m of list) {
        if (m && typeof m === 'object' && m.context_window == null) {
            m.context_window = DEFAULT_CONTEXT_WINDOW
        }
    }
    return Buffer.from(JSON.stringify(data))
}

const server = http.createServer((req, res) => {
    const isModelsList = req.method === 'GET' && req.url.startsWith('/v1/models')

    const headers = { ...req.headers, host: `${UPSTREAM_HOST}:${UPSTREAM_PORT}` }
    const upstream = http.request(
        { host: UPSTREAM_HOST, port: UPSTREAM_PORT, path: req.url, method: req.method, headers },
        (ur) => {
            if (isModelsList) {
                // Buffer + rewrite the model list to inject context_window.
                let body = ''
                ur.setEncoding('utf-8')
                ur.on('data', (c) => (body += c))
                ur.on('end', () => {
                    let out
                    try {
                        out = rewriteModels(body)
                    } catch {
                        out = Buffer.from(body)
                    }
                    const h = { ...ur.headers }
                    delete h['content-length']
                    res.writeHead(ur.statusCode || 200, h)
                    res.end(out)
                })
                return
            }
            // Transparent streaming passthrough (covers SSE /v1/messages).
            res.writeHead(ur.statusCode || 200, ur.headers)
            ur.pipe(res)
        }
    )
    upstream.on('error', (e) => {
        res.writeHead(502)
        res.end(`shim upstream error: ${e.message}`)
    })
    req.pipe(upstream)
})

server.listen(LISTEN_PORT, '0.0.0.0', () => {
    process.stdout.write(
        `gateway-model-meta-shim: :${LISTEN_PORT} → ${UPSTREAM_HOST}:${UPSTREAM_PORT} (context_window=${DEFAULT_CONTEXT_WINDOW})\n`
    )
})
