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
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import type { Context } from '@/tools/types'

describe('Documentation', { concurrent: false }, () => {
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

    describe('docs-search tool', () => {
        const searchTool = GENERATED_TOOL_MAP['docs-search']!()

        it.skip('should search documentation with valid query', async () => {
            const result = (await searchTool.handler(context, { query: 'feature flags' })) as { content: string }

            expect(typeof result.content).toBe('string')
            expect(result.content.length).toBeGreaterThan(0)
        })

        it.skip('should search for analytics documentation', async () => {
            const result = (await searchTool.handler(context, { query: 'analytics events tracking' })) as {
                content: string
            }

            expect(typeof result.content).toBe('string')
            expect(result.content.length).toBeGreaterThan(0)
        })

        it.skip('should handle empty query results', async () => {
            const result = (await searchTool.handler(context, {
                query: 'zxcvbnmasdfghjklqwertyuiop123456789',
            })) as { content: string }

            expect(typeof result.content).toBe('string')
        })
    })

    describe('Documentation search workflow', () => {
        it('should validate query parameter is required', async () => {
            const searchTool = GENERATED_TOOL_MAP['docs-search']!()

            await expect(searchTool.handler(context, {} as { query: string })).rejects.toBeTruthy()
        })
    })
})
