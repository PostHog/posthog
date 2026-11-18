import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/warehouse_sources'
import type { Context } from '@/tools/types'

// Agents name the source id `source_id` (the column name in the metadata tables) or
// `sourceId`, and the table id `schema_id` or `schemaId`, but the endpoints take `id`.
// Each alias must reach the handler as the `id` path parameter, or the call fails
// validation with a "missing required parameter: id" error.

const ID = '0196a1c2-1234-7abc-8def-0123456789ab'

function createMockContext(): { context: Context; request: ReturnType<typeof vi.fn> } {
    const request = vi.fn().mockResolvedValue({})
    const context = {
        api: { request },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('1') },
    } as unknown as Context
    return { context, request }
}

describe('warehouse source and schema id aliases', () => {
    describe.each([
        ['external-data-sources-retrieve', {}],
        ['external-data-sources-webhook-info-retrieve', {}],
        ['external-data-sources-partial-update', {}],
        ['external-data-sources-destroy', {}],
        ['external-data-sources-reload', {}],
        ['external-data-sources-refresh-schemas', {}],
        ['external-data-sources-bulk-update-schemas', { schemas: [] }],
        ['external-data-sources-repair-cdc-create', {}],
        ['external-data-sources-destinations-retrieve', {}],
    ])('%s', (toolName, requiredBody) => {
        const schema = GENERATED_TOOLS[toolName]!().schema

        it.each([
            ['id', { id: ID }],
            ['source_id', { source_id: ID }],
            ['sourceId', { sourceId: ID }],
        ])('accepts %s as the source id', (_label, input) => {
            const result = schema.safeParse({ ...requiredBody, ...input })
            expect(result.success).toBe(true)
            expect(result.data).toMatchObject({ id: ID })
            expect(result.data).not.toHaveProperty('source_id')
            expect(result.data).not.toHaveProperty('sourceId')
        })

        it('prefers id over an alias on conflict', () => {
            const result = schema.safeParse({ ...requiredBody, id: ID, source_id: 'other' })
            expect(result.data).toMatchObject({ id: ID })
        })

        it('still rejects a call with no identifier', () => {
            expect(schema.safeParse({}).success).toBe(false)
        })
    })

    describe.each([
        'external-data-schemas-retrieve',
        'external-data-schemas-partial-update',
        'external-data-schemas-reload',
        'external-data-schemas-resync',
        'external-data-schemas-cancel',
        'external-data-schemas-delete-data',
        'external-data-schemas-incremental-fields-create',
        'external-data-schemas-destinations-retrieve',
    ])('%s', (toolName) => {
        const schema = GENERATED_TOOLS[toolName]!().schema

        it.each([
            ['id', { id: ID }],
            ['schema_id', { schema_id: ID }],
            ['schemaId', { schemaId: ID }],
        ])('accepts %s as the schema id', (_label, input) => {
            expect(schema.safeParse(input).data).toMatchObject({ id: ID })
        })

        it('does not treat source_id as the schema id', () => {
            expect(schema.safeParse({ source_id: ID }).success).toBe(false)
        })
    })

    it('sends a source_id alias as the id path parameter', async () => {
        const { context, request } = createMockContext()
        const tool = GENERATED_TOOLS['external-data-sources-retrieve']!()

        const params = tool.schema.parse({ source_id: ID })
        await tool.handler(context, params)

        expect(request.mock.calls[0]![0]).toMatchObject({
            method: 'GET',
            path: `/api/projects/1/external_data_sources/${ID}/`,
        })
    })
})
