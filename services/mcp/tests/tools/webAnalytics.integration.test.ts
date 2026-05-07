import { beforeAll, describe, expect, it } from 'vitest'

import {
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    createTestClient,
    createTestContext,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/web_analytics'
import type { Context } from '@/tools/types'

describe('Web analytics weekly digest', { concurrent: false }, () => {
    let context: Context
    const tool = GENERATED_TOOLS['web-analytics-weekly-digest']!()

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    const METRIC_KEYS = ['visitors', 'pageviews', 'sessions', 'bounce_rate', 'avg_session_duration'] as const
    const TOP_LEVEL_KEYS = [...METRIC_KEYS, 'top_pages', 'top_sources', 'goals', 'dashboard_url']

    it('should default days to 7 and compare to true', () => {
        const parsed = tool.schema.parse({})

        expect(parsed).toEqual({ days: 7, compare: true })
    })

    it('should return digest with default params', async () => {
        const result = await tool.handler(context, tool.schema.parse({}))
        const response = parseToolResponse(result)

        for (const key of TOP_LEVEL_KEYS) {
            expect(response).toHaveProperty(key)
        }
        for (const metric of METRIC_KEYS) {
            expect(response[metric]).toHaveProperty('current')
        }
        expect(Array.isArray(response.top_pages)).toBe(true)
        expect(Array.isArray(response.top_sources)).toBe(true)
        expect(Array.isArray(response.goals)).toBe(true)
        expect(String(response.dashboard_url)).toContain('/web')
    })

    it('should omit period-over-period comparison when compare=false', async () => {
        const result = await tool.handler(context, tool.schema.parse({ compare: false }))
        const response = parseToolResponse(result)

        for (const metric of METRIC_KEYS) {
            expect(response[metric].previous).toBeNull()
            expect(response[metric].change).toBeNull()
        }
    })

    it('should reject days outside 1–90 at the API boundary', async () => {
        await expect(tool.handler(context, { days: 0, compare: true })).rejects.toThrow()
        await expect(tool.handler(context, { days: 91, compare: true })).rejects.toThrow()
    })
})
