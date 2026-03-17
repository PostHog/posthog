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
import { GENERATED_TOOLS } from '@/tools/generated/activity_logs'
import type { Context } from '@/tools/types'

describe('Activity Logs', { concurrent: false }, () => {
    let context: Context

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    describe('activity-logs-list tool', () => {
        const listTool = GENERATED_TOOLS['activity-logs-list']!()

        it('should list activity logs with default parameters', async () => {
            const result = await listTool.handler(context, {})
            const response = parseToolResponse(result)

            expect(response).toHaveProperty('results')
            expect(Array.isArray(response.results)).toBe(true)
            expect(response._posthogUrl).toContain('/activity')
        })

        it('should return results with expected structure', async () => {
            const result = await listTool.handler(context, { page: 1, page_size: 5 })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)

            if (response.results.length > 0) {
                const log = response.results[0]
                expect(log).toHaveProperty('id')
                expect(log).toHaveProperty('activity')
                expect(log).toHaveProperty('scope')
                expect(log).toHaveProperty('created_at')
                expect(log).toHaveProperty('user')
            }
        })

        it('should support page-based pagination', async () => {
            const page1 = await listTool.handler(context, { page: 1, page_size: 2 })
            const page1Data = parseToolResponse(page1)

            expect(Array.isArray(page1Data.results)).toBe(true)
            expect(page1Data.results.length).toBeLessThanOrEqual(2)

            if (page1Data.results.length === 2) {
                const page2 = await listTool.handler(context, { page: 2, page_size: 2 })
                const page2Data = parseToolResponse(page2)

                expect(Array.isArray(page2Data.results)).toBe(true)

                if (page2Data.results.length > 0) {
                    const page1Ids = page1Data.results.map((r: any) => r.id)
                    const page2Ids = page2Data.results.map((r: any) => r.id)
                    const overlap = page1Ids.filter((id: string) => page2Ids.includes(id))
                    expect(overlap).toHaveLength(0)
                }
            }
        })

        it('should filter by scope', async () => {
            const result = await listTool.handler(context, {
                scope: 'FeatureFlag',
                page: 1,
                page_size: 10,
            })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            for (const log of response.results) {
                expect(log.scope).toBe('FeatureFlag')
            }
        })

        it('should filter by multiple scopes', async () => {
            const result = await listTool.handler(context, {
                scopes: ['FeatureFlag', 'Insight'],
                page: 1,
                page_size: 10,
            })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            for (const log of response.results) {
                expect(['FeatureFlag', 'Insight']).toContain(log.scope)
            }
        })

        it('should filter by item_id', async () => {
            // First get a log to find a real item_id
            const seed = await listTool.handler(context, { page: 1, page_size: 1 })
            const seedData = parseToolResponse(seed)

            if (seedData.results.length === 0) {
                return
            }

            const targetItemId = seedData.results[0].item_id
            if (!targetItemId) {
                return
            }

            const result = await listTool.handler(context, {
                item_id: targetItemId,
                page: 1,
                page_size: 10,
            })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            for (const log of response.results) {
                expect(log.item_id).toBe(targetItemId)
            }
        })

        it('should return empty results for non-existent scope filter', async () => {
            // Use a valid scope but filter by an item_id that doesn't exist
            const result = await listTool.handler(context, {
                item_id: '999999999',
                scope: 'FeatureFlag',
                page: 1,
                page_size: 10,
            })
            const response = parseToolResponse(result)

            expect(Array.isArray(response.results)).toBe(true)
            expect(response.results).toHaveLength(0)
        })
    })
})
