/**
 * Tests for the generated `cohorts-replace-static-members` tool.
 *
 * The tool reuses the cohort partial-update endpoint but is destructive: it removes members the
 * query no longer matches. These tests pin what the YAML config decides and the backend can't
 * see: the only inputs are the cohort id and the query, and every request carries
 * population_mode=replace.
 */
import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/cohorts'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PROJECT_ID = '2'
const QUERY = { kind: 'HogQLQuery', query: 'SELECT person_id FROM events' }

function getTool(): ToolBase<ZodObjectAny> {
    return (GENERATED_TOOLS['cohorts-replace-static-members'] as () => ToolBase<ZodObjectAny>)()
}

describe('cohorts-replace-static-members', () => {
    it('accepts only the cohort id and the query', () => {
        const schema = getTool().schema as z.ZodObject<z.ZodRawShape>

        expect(Object.keys(schema.shape).sort()).toEqual(['id', 'query'])
        // Without a query the endpoint returns a 400, so the schema refuses the call first.
        expect(schema.safeParse({ id: '7' }).success).toBe(false)
    })

    it('PATCHes the cohort with the query and population_mode=replace', async () => {
        const requestMock = vi.fn().mockResolvedValue({ id: 7 })
        const context = {
            api: { request: requestMock, getProjectBaseUrl: () => 'https://app.posthog.test/project/2' } as any,
            stateManager: { getProjectId: vi.fn().mockResolvedValue(PROJECT_ID) } as any,
        } as Context
        const tool = getTool()

        await tool.handler(context, tool.schema.parse({ id: '7', query: QUERY }))

        expect(requestMock).toHaveBeenCalledWith({
            method: 'PATCH',
            path: '/api/projects/2/cohorts/7/',
            body: { query: QUERY, population_mode: 'replace' },
        })
    })
})
