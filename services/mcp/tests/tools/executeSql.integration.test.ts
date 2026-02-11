import { afterEach, beforeAll, describe, expect, it } from 'vitest'

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

    it('should execute a simple count query', async () => {
        const result = await tool.handler(context, {
            query: 'SELECT count() AS total FROM events',
        })

        expect(typeof result).toBe('string')
        const parsed = JSON.parse(result)
        expect(parsed).toHaveProperty('results')
        expect(parsed).toHaveProperty('columns')
        expect(parsed.columns).toContain('total')
        expect(Array.isArray(parsed.results)).toBe(true)
    })

    it('should execute a query with a WHERE clause', async () => {
        const result = await tool.handler(context, {
            query: "SELECT event, count() AS cnt FROM events WHERE event = '$pageview' GROUP BY event",
        })

        const parsed = JSON.parse(result)
        expect(parsed.columns).toContain('event')
        expect(parsed.columns).toContain('cnt')
    })

    it('should execute a query with date filters', async () => {
        const result = await tool.handler(context, {
            query: "SELECT event, count() AS cnt FROM events WHERE timestamp >= now() - INTERVAL 7 DAY AND event = '$pageview' GROUP BY event ORDER BY cnt DESC LIMIT 5",
        })

        const parsed = JSON.parse(result)
        expect(parsed).toHaveProperty('results')
        expect(parsed).toHaveProperty('columns')
    })

    it('should throw on invalid SQL', async () => {
        await expect(tool.handler(context, { query: 'SELEC INVALID SYNTAX' })).rejects.toThrow()
    })

    it('should throw on querying a non-existent table', async () => {
        await expect(tool.handler(context, { query: 'SELECT * FROM non_existent_table_xyz' })).rejects.toThrow()
    })
})
