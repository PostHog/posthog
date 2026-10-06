import path from 'path'
import { describe, expect, it } from 'vitest'
import { parse as parseYaml } from 'yaml'

import { buildAddedTool, findCandidates, mergeWithExisting, renderCategoryYaml } from '../../scripts/scaffold-yaml'
import type { OpenApiSpec } from '../../scripts/scaffold-yaml'
import { CategoryConfigSchema } from '../../scripts/yaml-config-schema'
import type { CategoryConfig } from '../../scripts/yaml-config-schema'

const spec: OpenApiSpec = {
    paths: {
        '/api/environments/{project_id}/things/': {
            get: { operationId: 'things_list', 'x-product': ['things'], summary: 'List things' },
        },
        '/api/projects/{project_id}/things/': {
            get: { operationId: 'things_list_2', 'x-product': ['things'], summary: 'List things' },
            post: { operationId: 'things_create', 'x-product': ['things'], description: 'Create a thing.' },
        },
        '/api/projects/{project_id}/things/{id}/': {
            delete: { operationId: 'things_destroy', 'x-product': ['things'] },
        },
        '/api/projects/{project_id}/others/': {
            get: { operationId: 'others_list', 'x-product': ['others'] },
        },
    },
}

function category(tools: Record<string, unknown>): CategoryConfig {
    return CategoryConfigSchema.parse({ category: 'Things', feature: 'things', url_prefix: '/things', tools })
}

function validIds(product: string): Set<string> {
    const ids = Object.values(spec.paths).flatMap((methods) =>
        Object.values(methods)
            .filter((op) => op['x-product']?.includes(product))
            .map((op) => op.operationId)
    )
    return new Set(ids)
}

const thingsOps = [
    { operationId: 'things_list', method: 'GET', path: '/api/projects/{project_id}/things/' },
    { operationId: 'things_create', method: 'POST', path: '/api/projects/{project_id}/things/' },
]

describe('scaffold-yaml', () => {
    it('does not add entries for operations that have none', () => {
        const existing = category({ 'things-list': { operation: 'things_list', enabled: true } })

        const { content } = mergeWithExisting(existing, thingsOps, 'things', validIds('things'))

        expect(Object.keys(parseYaml(content).tools)).toEqual(['things-list'])
    })

    it.each([
        {
            name: 'keeps an enabled tool and reports it as lost',
            config: { operation: 'gone_list', enabled: true },
            subset: false,
            kept: true,
            reported: 'lostEnabledTools',
        },
        {
            name: 'drops a disabled tool and reports it as dropped',
            config: { operation: 'gone_list', enabled: false, disabled_reason: 'Superseded by things-list' },
            subset: false,
            kept: false,
            reported: 'droppedDisabledTools',
        },
        {
            name: 'keeps a subset file tool and reports it as unmatched',
            config: { operation: 'gone_list', enabled: false, disabled_reason: 'Superseded by things-list' },
            subset: true,
            kept: true,
            reported: 'unmatchedTools',
        },
    ] as const)('$name when its operation is gone', ({ config, subset, kept, reported }) => {
        const existing = category({ 'gone-list': config })

        const result = mergeWithExisting(existing, thingsOps, 'things', validIds('things'), subset)

        expect('gone-list' in parseYaml(result.content).tools).toBe(kept)
        expect(result[reported]).toEqual([expect.stringMatching(/^gone-list \(gone_list\)/)])
    })

    it.each([
        {
            name: 'drops a disabled entry without disabled_reason',
            config: { operation: 'things_list', enabled: false },
            kept: false,
        },
        {
            name: 'keeps a disabled entry with disabled_reason',
            config: { operation: 'things_list', enabled: false, disabled_reason: 'Superseded by things-search' },
            kept: true,
        },
    ])('$name while its operation exists', ({ config, kept }) => {
        const existing = category({ 'things-list': config })

        const result = mergeWithExisting(existing, thingsOps, 'things', validIds('things'))

        expect('things-list' in parseYaml(result.content).tools).toBe(kept)
        expect(result.droppedDisabledTools).toEqual(kept ? [] : ['things-list (things_list): no disabled_reason'])
    })

    it('lists operations without an entry, deduplicated and sorted', () => {
        const candidates = findCandidates(spec, 'things', new Set(['things_destroy']))

        expect(candidates.map((op) => [op.operationId, op.method, op.path])).toEqual([
            ['things_create', 'POST', '/api/projects/{project_id}/things/'],
            ['things_list', 'GET', '/api/projects/{project_id}/things/'],
        ])
    })

    it('adds an enabled entry that the schema accepts', () => {
        const existing = category({})

        const { toolName, entry } = buildAddedTool(spec, 'things', 'things_create', new Set(), existing)
        const content = renderCategoryYaml(existing, 'things', { ...existing.tools, [toolName]: entry })

        expect(CategoryConfigSchema.parse(parseYaml(content)).tools).toEqual({
            'things-create': { operation: 'things_create', enabled: true },
        })
    })

    it.each([
        { name: 'the default file', file: '../../products/error_tracking/mcp/tools.yaml', flag: undefined },
        {
            name: 'an extra file',
            file: '../../products/error_tracking/mcp/error_tracking_alerts.yaml',
            flag: '--file ../../products/error_tracking/mcp/error_tracking_alerts.yaml',
        },
    ])('names the target file in the add command only for $name', ({ file, flag }) => {
        const content = renderCategoryYaml(category({}), 'error_tracking', {}, path.resolve(__dirname, '../..', file))
        const addLine = content.split('\n').find((line) => line.startsWith('# Add one:'))

        expect(addLine).toBe(
            `# Add one: pnpm --filter=@posthog/mcp run scaffold-yaml -- --add <operationId> --product error_tracking${flag ? ` ${flag}` : ''}`
        )
    })

    it.each([
        { name: 'an unknown operation', operationId: 'missing_list', claimed: [], error: /not in the OpenAPI schema/ },
        { name: "another product's operation", operationId: 'others_list', claimed: [], error: /not attributed/ },
        {
            name: 'an operation that already has an entry',
            operationId: 'things_list_2',
            claimed: ['things_list'],
            error: /already has a YAML entry/,
        },
    ])('rejects $name', ({ operationId, claimed, error }) => {
        expect(() => buildAddedTool(spec, 'things', operationId, new Set(claimed), category({}))).toThrow(error)
    })
})
