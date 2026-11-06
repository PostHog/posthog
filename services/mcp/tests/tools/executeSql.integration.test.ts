import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import { buildToolResultPayload } from '@/lib/build-tool-result'
import {
    type CreatedResources,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    cleanupResources,
    createTestClient,
    createTestContext,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import executeSqlTool from '@/tools/posthogAiTools/executeSql'
import type { Context } from '@/tools/types'

describe('execute-sql', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
        actions: [],
        cohorts: [],
    }

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        await cleanupResources(context.api, TEST_PROJECT_ID!, createdResources)
    })

    const tool = executeSqlTool()

    it('should execute a simple query', async () => {
        const result = await tool.handler(context, {
            query: "SELECT 'test_string'",
            truncate: true,
        })

        const payload = buildToolResultPayload({ handlerResult: result, toolName: 'execute-sql', params: {} })
        expect(payload.content[0]?.text).toContain('test_string')
    })

    it('should execute a query with a WHERE clause', async () => {
        const result = await tool.handler(context, {
            query: "SELECT event, count() AS cnt FROM events WHERE event = '$pageview' GROUP BY event",
            truncate: true,
        })

        const payload = buildToolResultPayload({ handlerResult: result, toolName: 'execute-sql', params: {} })
        expect(payload.content[0]?.text).toContain('event')
        expect(payload.content[0]?.text).toContain('cnt')
    })

    it('should execute a query with date filters', async () => {
        const result = await tool.handler(context, {
            query: "SELECT event, count() AS cnt FROM events WHERE timestamp >= now() - INTERVAL 7 DAY AND event = '$pageview' GROUP BY event ORDER BY cnt DESC LIMIT 5",
            truncate: false,
        })

        const payload = buildToolResultPayload({ handlerResult: result, toolName: 'execute-sql', params: {} })
        expect(typeof payload.content[0]?.text).toBe('string')
    })

    it('should throw on invalid SQL', async () => {
        await expect(tool.handler(context, { query: 'SELEC INVALID SYNTAX', truncate: true })).rejects.toThrow()
    })

    it('should throw on querying a non-existent table', async () => {
        await expect(
            tool.handler(context, { query: 'SELECT * FROM non_existent_table_xyz', truncate: true })
        ).rejects.toThrow()
    })
})
