import { afterEach, describe, expect, it } from 'vitest'

import { buildCliCatalog } from '@/cli/catalog/build'
import { loadCatalog } from '@/cli/catalog/load'
import { createApiToolLibrary } from '@/cli/library'
import { setCatalogToolDefinitions } from '@/tools/toolDefinitions'

const TOOL = 'annotations-list'

function catalogWith(change: (entry: Record<string, any>) => void, name = TOOL): Record<string, any> {
    const catalog = structuredClone(buildCliCatalog('test-build')) as Record<string, any>
    const entry = catalog.tools.find((tool: { name: string }) => tool.name === name)
    change(entry)
    return catalog
}

describe('CLI catalog loading', () => {
    afterEach(() => {
        setCatalogToolDefinitions({})
    })

    it.each([
        ['an unknown field', (entry: any) => (entry.retries = 3), 'unknown field retries'],
        [
            'an unknown param location',
            (entry: any) => (entry.request.headers = [{ param: 'x', key: 'X' }]),
            'unknown field request.headers',
        ],
        [
            'an unknown post-processing step',
            (entry: any) => (entry.response.redact = ['email']),
            'unknown field response.redact',
        ],
        [
            'an unknown kind of query mapping',
            (entry: any) => (entry.request.query[0].location = 'cookie'),
            'unknown field request.query.0.location',
        ],
        [
            'a hook this build lacks',
            (entry: any) => entry.requires.push('hook:future/newHooks'),
            'needs hook:future/newHooks',
        ],
        ['a capability this build lacks', (entry: any) => entry.requires.push('streaming'), 'needs streaming'],
    ])('drops an entry with %s and reports why', (_name, change, reason) => {
        const loaded = loadCatalog(catalogWith(change))

        expect(loaded).toMatchObject({ ok: true, dropped: [{ name: TOOL, reason: expect.stringContaining(reason) }] })
        expect(loaded.ok && loaded.entries.map((entry) => entry.name)).not.toContain(TOOL)
    })

    it('ignores a catalog in another format version', () => {
        const loaded = loadCatalog({ ...buildCliCatalog(null), schemaVersion: 2 })

        expect(loaded).toEqual({ ok: false, reason: expect.stringContaining('format 2') })
    })

    it('never lets a catalog entry replace a hand-written tool', () => {
        const loaded = loadCatalog(
            catalogWith(() => {}),
            new Set([TOOL])
        )

        expect(loaded.ok && loaded.dropped).toEqual([{ name: TOOL, reason: 'another tool already has this name' }])
    })

    it('runs the downloaded definition of a tool, and the compiled-in one when its entry is dropped', () => {
        const compiledSummary = createApiToolLibrary()
            .tools()
            .find((tool) => tool.name === TOOL)!.summary
        const changed = catalogWith((entry) => (entry.definition.summary = 'Downloaded summary'))

        const downloaded = createApiToolLibrary({ catalog: changed })
        expect(downloaded.tools().find((tool) => tool.name === TOOL)?.summary).toBe('Downloaded summary')
        expect(downloaded.catalog()).toMatchObject({ source: 'downloaded', build: 'test-build', dropped: [] })

        setCatalogToolDefinitions({})
        const broken = catalogWith((entry) => {
            entry.definition.summary = 'Downloaded summary'
            entry.response.redact = ['email']
        })
        const fallback = createApiToolLibrary({ catalog: broken })
        expect(fallback.tools().find((tool) => tool.name === TOOL)?.summary).toBe(compiledSummary)
        expect(fallback.catalog().dropped).toEqual([
            { name: TOOL, reason: 'unknown field response.redact', builtIn: true },
        ])
    })

    it('adds a tool the compiled-in catalog does not have', () => {
        const catalog = catalogWith(() => {})
        const copy = structuredClone(catalog.tools.find((tool: { name: string }) => tool.name === TOOL))
        catalog.tools.push({ ...copy, name: 'annotations-list-next' })

        const library = createApiToolLibrary({ catalog })

        expect(library.tools().map((tool) => tool.name)).toContain('annotations-list-next')
    })

    it('serves the compiled-in tools when the whole catalog is ignored', () => {
        const library = createApiToolLibrary({ catalog: { ...buildCliCatalog(null), schemaVersion: 99 } })

        expect(library.catalog()).toMatchObject({ source: 'bundled', rejected: expect.stringContaining('format 99') })
        expect(library.tools().length).toBe(createApiToolLibrary().tools().length)
    })
})
