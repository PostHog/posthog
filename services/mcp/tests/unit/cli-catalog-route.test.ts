import { Hono } from 'hono'
import { gunzipSync } from 'node:zlib'
import { describe, expect, it } from 'vitest'

import { loadCatalog } from '@/cli/catalog/load'
import { CATALOG_SCHEMA_VERSION } from '@/cli/catalog/schema'
import { cliCatalogHandler } from '@/hono/cli-catalog-route'
import { GENERATED_TOOL_MAP } from '@/tools/generated'

describe('CLI catalog route', () => {
    const app = new Hono()
    app.get('/cli/catalog.json', cliCatalogHandler)

    it('serves a gzipped catalog of this deploy that the CLI loads whole, and answers 304 to its ETag', async () => {
        const response = await app.request('/cli/catalog.json', { headers: { 'Accept-Encoding': 'gzip' } })

        expect(response.status).toBe(200)
        expect(response.headers.get('Content-Encoding')).toBe('gzip')
        const catalog = JSON.parse(gunzipSync(Buffer.from(await response.arrayBuffer())).toString('utf8'))
        expect(catalog.schemaVersion).toBe(CATALOG_SCHEMA_VERSION)
        expect(catalog.tools.every((tool: { name: string }) => tool.name in GENERATED_TOOL_MAP)).toBe(true)
        const loaded = loadCatalog(catalog)
        expect(loaded.ok && { tools: loaded.entries.length, dropped: loaded.dropped }).toEqual({
            tools: catalog.tools.length,
            dropped: [],
        })

        const etag = response.headers.get('ETag')!
        const again = await app.request('/cli/catalog.json', { headers: { 'If-None-Match': etag } })
        expect(again.status).toBe(304)
    })
})
