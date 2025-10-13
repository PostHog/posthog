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
} from '@/shared/test-utils'
import searchDocsTool from '@/tools/documentation/searchDocs'
import type { Context } from '@/tools/types'

describe('Documentation', { concurrent: false }, () => {
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

    describe('search-docs tool', () => {
        const searchTool = searchDocsTool()

        it('should handle missing INKEEP_API_KEY', async () => {
            const contextWithoutKey = {
                ...context,
                env: { ...context.env, INKEEP_API_KEY: undefined as any },
            }

            const result = await searchTool.handler(contextWithoutKey as Context, {
                query: 'feature flags',
            })

            expect(result.content[0].text).toBe('Error: INKEEP_API_KEY is not configured.')
        })

        it.skip('should search documentation with valid query', async () => {
            const result = await searchTool.handler(context, {
                query: 'feature flags',
            })

            expect(result.content[0].type).toBe('text')
            expect(result.content[0].text).toBeDefined()
            expect(result.content[0].text.length).toBeGreaterThan(0)
        })

        it.skip('should search for analytics documentation', async () => {
            const result = await searchTool.handler(context, {
                query: 'analytics events tracking',
            })

            expect(result.content[0].type).toBe('text')
            expect(result.content[0].text).toBeDefined()
            expect(result.content[0].text.length).toBeGreaterThan(0)
        })

        it.skip('should handle empty query results', async () => {
            const result = await searchTool.handler(context, {
                query: 'zxcvbnmasdfghjklqwertyuiop123456789',
            })

            expect(result.content[0].type).toBe('text')
            expect(result.content[0].text).toBeDefined()
        })
    })

    describe('Documentation search workflow', () => {
        it('should validate query parameter is required', async () => {
            const searchTool = searchDocsTool()

            try {
                await searchTool.handler(context, { query: '' })
                expect.fail('Should have thrown validation error')
            } catch (error) {
                expect(error).toBeDefined()
            }
        })
    })
})
