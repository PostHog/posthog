import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import {
    validateEnvironmentVariables,
    createTestClient,
    createTestContext,
    setActiveProjectAndOrg,
    cleanupResources,
    TEST_PROJECT_ID,
    TEST_ORG_ID,
    type CreatedResources,
    parseToolResponse,
} from '@/shared/test-utils'
import getLLMCostsTool from '@/tools/llmAnalytics/getLLMCosts'
import type { Context } from '@/tools/types'

describe('LLM Analytics', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
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

    describe('get-llm-costs tool', () => {
        const costsTool = getLLMCostsTool()

        it('should get LLM costs with default days (6 days)', async () => {
            const result = await costsTool.handler(context, {
                projectId: Number(TEST_PROJECT_ID),
            })
            const costsData = parseToolResponse(result)

            expect(Array.isArray(costsData)).toBe(true)
        })

        it('should get LLM costs for custom time period', async () => {
            const result = await costsTool.handler(context, {
                projectId: Number(TEST_PROJECT_ID),
                days: 30,
            })
            const costsData = parseToolResponse(result)

            expect(Array.isArray(costsData)).toBe(true)
        })

        it('should get LLM costs for single day', async () => {
            const result = await costsTool.handler(context, {
                projectId: Number(TEST_PROJECT_ID),
                days: 1,
            })
            const costsData = parseToolResponse(result)

            expect(Array.isArray(costsData)).toBe(true)
        })
    })

    describe('LLM Analytics workflow', () => {
        it('should support getting costs for different time periods', async () => {
            const costsTool = getLLMCostsTool()

            const weekResult = await costsTool.handler(context, {
                projectId: Number(TEST_PROJECT_ID),
                days: 7,
            })
            const weekData = parseToolResponse(weekResult)
            expect(Array.isArray(weekData)).toBe(true)

            const monthResult = await costsTool.handler(context, {
                projectId: Number(TEST_PROJECT_ID),
                days: 30,
            })
            const monthData = parseToolResponse(monthResult)
            expect(Array.isArray(monthData)).toBe(true)
        })
    })
})
