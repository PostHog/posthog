import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/warehouse_sources'
import type { Context } from '@/tools/types'

const item = {
    id: '00000000-0000-4000-8000-000000000002',
    status: 'skipped',
    created_by: { email: 'person@example.com' },
    proposal: {
        source_type: 'Postgres',
        prefill: { host: 'db.example.com', user: 'reader' },
        schemas: [
            {
                name: 'orders',
                vendor_table: 'public.orders',
                disabled_columns: ['notes'],
                row_filters: [{ column: 'region', operator: '=', values: ['eu'] }],
                alternative_names: ['order'],
            },
        ],
    },
}

describe('Generated warehouse migration tools', () => {
    it.each([
        ['warehouse-migration-item-skip', item],
        ['warehouse-migration-items-list', { count: 1, next: null, previous: null, results: [item] }],
    ])('%s leaves out who started the migration and the connection settings', async (name, response) => {
        const context = {
            api: {
                request: vi.fn().mockResolvedValue(structuredClone(response)),
                getProjectBaseUrl: (projectId: string) => `https://us.posthog.com/project/${projectId}`,
            },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context
        const tool = GENERATED_TOOLS[name]!()
        const params = tool.schema.parse({
            id: '00000000-0000-4000-8000-000000000001',
            item_id: item.id,
        })

        const result = JSON.stringify(await tool.handler(context, params))

        expect(result).toContain('public.orders')
        for (const leaked of ['person@example.com', 'db.example.com', 'region', 'notes', 'alternative_names']) {
            expect(result).not.toContain(leaked)
        }
    })
})
