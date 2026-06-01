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
import { GENERATED_TOOLS } from '@/tools/generated/workflows'
import type { Context } from '@/tools/types'

describe('Workflows', { concurrent: false }, () => {
    let context: Context

    const listTool = GENERATED_TOOLS['workflows-list']!()
    const getTool = GENERATED_TOOLS['workflows-get']!()
    const logsTool = GENERATED_TOOLS['hog-flows-logs-retrieve']!()
    const metricsTool = GENERATED_TOOLS['hog-flows-metrics-retrieve']!()

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    describe('workflows-list tool', () => {
        it('should list workflows and return paginated structure', async () => {
            const result = await listTool.handler(context, {})
            const data = parseToolResponse(result)

            expect(typeof data.count).toBe('number')
            expect(Array.isArray(data.results)).toBe(true)
        })

        it('should respect the limit parameter', async () => {
            const result = await listTool.handler(context, { limit: 1 })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            expect(data.results.length).toBeLessThanOrEqual(1)
        })

        it('should respect the offset parameter', async () => {
            const allResult = await listTool.handler(context, { limit: 100 })
            const all = parseToolResponse(allResult)

            const pagedResult = await listTool.handler(context, { offset: 1, limit: 100 })
            const paged = parseToolResponse(pagedResult)

            // Paging forward by one should yield at most (total − 1) results.
            expect(paged.results.length).toBeLessThanOrEqual(Math.max(0, all.results.length - 1))
        })
    })

    describe('workflows-get tool', () => {
        it('should return a valid workflow when given a UUID from the list', async () => {
            const listResult = await listTool.handler(context, {})
            const { results: workflows } = parseToolResponse(listResult)

            if (workflows.length === 0) {
                // No workflows in this environment — nothing to fetch.
                return
            }

            const firstId: string = workflows[0].id
            const result = await getTool.handler(context, { id: firstId })
            const workflow = parseToolResponse(result)

            expect(workflow.id).toBe(firstId)
            expect(workflow.name == null || typeof workflow.name === 'string').toBe(true)
            expect(typeof workflow.version).toBe('number')
            expect(['draft', 'active', 'archived']).toContain(workflow.status)
            expect(Array.isArray(workflow.actions)).toBe(true)
            expect(workflow).toHaveProperty('trigger')
            expect(workflow).toHaveProperty('edges')
            expect(workflow).toHaveProperty('exit_condition')
        })

        it('should return an error for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()

            await expect(getTool.handler(context, { id: absentId })).rejects.toThrow()
        })
    })

    describe('hog-flows-logs-retrieve tool', () => {
        it('should return log entries for a workflow', async () => {
            const listResult = await listTool.handler(context, {})
            const { results: workflows } = parseToolResponse(listResult)

            if (workflows.length === 0) {
                return
            }

            const result = await logsTool.handler(context, { id: workflows[0].id })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
        })

        it('should accept limit and level parameters', async () => {
            const listResult = await listTool.handler(context, {})
            const { results: workflows } = parseToolResponse(listResult)

            if (workflows.length === 0) {
                return
            }

            const result = await logsTool.handler(context, {
                id: workflows[0].id,
                limit: 5,
                level: 'ERROR',
            })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.results)).toBe(true)
            expect(data.results.length).toBeLessThanOrEqual(5)
        })

        it('should throw for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()
            await expect(logsTool.handler(context, { id: absentId })).rejects.toThrow()
        })
    })

    describe('hog-flows-metrics-retrieve tool', () => {
        it('should return metrics for a workflow', async () => {
            const listResult = await listTool.handler(context, {})
            const { results: workflows } = parseToolResponse(listResult)

            if (workflows.length === 0) {
                return
            }

            const result = await metricsTool.handler(context, { id: workflows[0].id })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.labels)).toBe(true)
            expect(Array.isArray(data.series)).toBe(true)
        })

        it('should accept interval parameter', async () => {
            const listResult = await listTool.handler(context, {})
            const { results: workflows } = parseToolResponse(listResult)

            if (workflows.length === 0) {
                return
            }

            const result = await metricsTool.handler(context, {
                id: workflows[0].id,
                interval: 'day',
            })
            const data = parseToolResponse(result)

            expect(Array.isArray(data.labels)).toBe(true)
            expect(Array.isArray(data.series)).toBe(true)
        })

        it('should throw for a non-existent UUID', async () => {
            const absentId = crypto.randomUUID()
            await expect(metricsTool.handler(context, { id: absentId })).rejects.toThrow()
        })
    })
})
