import { createHash } from 'node:crypto'
import { gzipSync } from 'node:zlib'

import { buildCliCatalog } from '@/cli/catalog/build'
import { getMCPServerBuild } from '@/lib/posthog/client'

import type { HonoCtx } from './types'

interface CatalogBody {
    json: string
    gzip: Buffer
    etag: string
}

let cached: CatalogBody | undefined

// Built once per process from the tool code this server runs, so the catalog hog downloads always
// matches the tools this deploy serves over MCP and the API it was built against.
function catalogBody(): CatalogBody {
    if (!cached) {
        const json = JSON.stringify(buildCliCatalog(getMCPServerBuild() ?? null))
        cached = {
            json,
            gzip: gzipSync(json),
            etag: `"${createHash('sha256').update(json).digest('hex').slice(0, 32)}"`,
        }
    }
    return cached
}

export function cliCatalogHandler(c: HonoCtx): Response {
    const body = catalogBody()
    const headers: Record<string, string> = {
        'Cache-Control': 'public, max-age=300',
        ETag: body.etag,
        Vary: 'Accept-Encoding',
    }
    if (c.req.header('If-None-Match') === body.etag) {
        return new Response(null, { status: 304, headers })
    }

    const acceptsGzip = /\bgzip\b/.test(c.req.header('Accept-Encoding') ?? '')
    return new Response(acceptsGzip ? new Uint8Array(body.gzip) : body.json, {
        status: 200,
        headers: {
            ...headers,
            'Content-Type': 'application/json',
            ...(acceptsGzip ? { 'Content-Encoding': 'gzip' } : {}),
        },
    })
}
