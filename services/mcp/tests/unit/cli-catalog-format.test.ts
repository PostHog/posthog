import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { catalogTool } from '@/cli/catalog/executor'
import { CATALOG_SCHEMA_VERSION, type CatalogEntry, CatalogHttpToolSchema } from '@/cli/catalog/schema'
import type { Context } from '@/tools/types'

const definition = {
    category: 'Test',
    feature: 'test',
    summary: 'Test tool',
    title: 'Test tool',
    description: 'A tool for the format snapshot.',
    required_scopes: [],
    annotations: { destructiveHint: false, idempotentHint: true, openWorldHint: true, readOnlyHint: true },
}

function plan(
    name: string,
    request: Partial<CatalogEntry['request']>,
    response: Partial<CatalogEntry['response']>,
    input: Partial<CatalogEntry['input']>,
    inputSchema: Record<string, unknown>
): CatalogEntry {
    return {
        name,
        kind: 'http',
        requires: [],
        hooks: null,
        uiApp: null,
        request: {
            method: 'GET',
            path: '/api/projects/{project_id}/things/',
            pathParams: [],
            fallbacks: [],
            query: null,
            body: null,
            injectBody: {},
            softDelete: null,
            transformBody: false,
            ...request,
        },
        response: {
            list: false,
            filter: null,
            stripNulls: false,
            enrich: null,
            agentNote: null,
            informational: null,
            textInclude: [],
            ...response,
        },
        input: { aliases: {}, casts: {}, validators: [], ...input },
        definition,
        inputSchema: { type: 'object', ...inputSchema },
    }
}

const PLANS: [CatalogEntry, Record<string, unknown>][] = [
    [
        plan(
            'list-with-csv-query',
            {
                query: [
                    { param: 'tags', key: 'tag', csv: true },
                    { param: 'limit', key: 'limit', csv: false },
                ],
            },
            {
                list: true,
                filter: { kind: 'omit', fields: ['secret'], expandable: ['detail'] },
                enrich: { kind: 'list', baseUrl: '/things' },
            },
            {},
            {
                properties: {
                    tags: { type: 'array', items: { type: 'string' } },
                    limit: { type: 'integer', default: 50 },
                    expand: { type: 'array', items: { type: 'string' } },
                },
            }
        ),
        { tags: ['a', 'b'], expand: ['detail'] },
    ],
    [
        plan(
            'create-with-body-and-aliases',
            {
                method: 'POST',
                body: [
                    { param: 'name', key: 'name' },
                    { param: 'label', key: 'display_label' },
                ],
                injectBody: { source: 'cli' },
            },
            {
                filter: { kind: 'pick', fields: ['id', 'name'], selectable: true },
                stripNulls: true,
                agentNote: 'Note.',
                enrich: {
                    kind: 'item',
                    baseUrl: '/things',
                    joiner: '/',
                    prefix: '',
                    field: 'id',
                    suffix: '',
                    source: 'result',
                },
            },
            { aliases: { name: ['title'] }, casts: { count: 'castStringToInt' } },
            {
                properties: {
                    name: { type: 'string' },
                    label: { type: 'string', enum: ['a', 'b'], default: 'a' },
                    count: { type: 'integer' },
                    fields: { type: 'array', items: { type: 'string' } },
                },
            }
        ),
        { title: 'Thing', count: '3', fields: ['id'] },
    ],
    [
        plan(
            'soft-delete-with-path-and-fallback',
            {
                method: 'PATCH',
                path: '/api/organizations/{organization_id}/things/{id}/',
                pathParams: ['id'],
                fallbacks: [{ param: 'org', scope: 'orgId' }],
                softDelete: 'archived',
            },
            { informational: { tag: 'thing-reference', purpose: 'Reference only.' }, textInclude: ['id'] },
            {},
            { properties: { id: { type: 'string' }, org: { type: 'string' } }, required: ['id'] }
        ),
        { id: 'x/y' },
    ],
    [
        plan(
            'list-with-item-links',
            {},
            {
                list: true,
                enrich: {
                    kind: 'list_items',
                    baseUrl: '/things',
                    joiner: '',
                    prefix: '?id=',
                    field: 'id',
                    suffix: '#top',
                },
            },
            {},
            {
                properties: {
                    kind: {
                        anyOf: [
                            { type: 'object', properties: { type: { const: 'a', default: 'a' } } },
                            { type: 'null' },
                        ],
                    },
                },
            }
        ),
        { kind: {} },
    ],
]

function fakeContext(): { context: Context; calls: unknown[] } {
    const calls: unknown[] = []
    const context = {
        api: {
            getProjectBaseUrl: (projectId: unknown) => `https://us.posthog.com/project/${projectId}`,
            request: async (options: unknown) => {
                calls.push(options)
                return {
                    id: 1,
                    name: 'Thing',
                    secret: 's',
                    detail: 'd',
                    empty: null,
                    results: [{ id: 1, secret: 's', detail: 'd' }],
                }
            },
        },
        stateManager: { getProjectId: async () => '7', getOrgID: async () => 'org-1' },
    } as unknown as Context
    return { context, calls }
}

describe('CLI catalog format', () => {
    // A change here means plans written in this format run differently. Old hogs keep running them the
    // old way, so bump CATALOG_SCHEMA_VERSION, which makes them ignore the catalog. Update the snapshot
    // without a bump only when old hogs read every existing plan the same way.
    it(`format ${CATALOG_SCHEMA_VERSION} runs plans the same way`, async () => {
        const runs = []
        for (const [entry, input] of PLANS) {
            const tool = catalogTool(entry)
            const { context, calls } = fakeContext()
            const result = await tool.handler(context, tool.schema.parse(input))
            runs.push({ name: entry.name, requests: calls, result })
        }

        await expect(
            JSON.stringify({ planSchema: z.toJSONSchema(CatalogHttpToolSchema), runs }, null, 4) + '\n'
        ).toMatchFileSnapshot(`./__snapshots__/cli-catalog-format-v${CATALOG_SCHEMA_VERSION}.txt`)
    })
})
