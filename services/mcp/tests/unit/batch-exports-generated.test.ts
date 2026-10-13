import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/batch_exports'
import type { Context } from '@/tools/types'

describe('Generated batch export tools', () => {
    it.each([
        ['batch-export-create', 'POST'],
        ['batch-export-update', 'PATCH'],
    ])('%s forwards the HogQL query', async (name, method) => {
        const request = vi.fn().mockResolvedValue({})
        const context = {
            api: { request },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context
        const hogqlQuery = 'SELECT event FROM events WHERE timestamp < {data_interval_end}'
        const tool = GENERATED_TOOLS[name]!()
        const params = tool.schema.parse({
            id: '00000000-0000-4000-8000-000000000001',
            name: 'Test export',
            model: 'hogql',
            interval: 'hour',
            destination: { type: 'BigQuery', integration_id: 1, config: { dataset_id: 'exports' } },
            hogql_query: hogqlQuery,
        })

        await tool.handler(context, params)

        expect(request).toHaveBeenCalledWith(
            expect.objectContaining({ method, body: expect.objectContaining({ hogql_query: hogqlQuery }) })
        )
    })
})
