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
import listErrorsTool from '@/tools/errorTracking/listErrors'
import errorDetailsTool from '@/tools/errorTracking/errorDetails'
import type { Context } from '@/tools/types'
import { OrderByErrors, OrderDirectionErrors, StatusErrors } from '@/schema/errors'

describe('Error Tracking', { concurrent: false }, () => {
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

    describe('list-errors tool', () => {
        const listTool = listErrorsTool()

        it('should list errors with default parameters', async () => {
            const result = await listTool.handler(context, {})
            const errorData = parseToolResponse(result)

            expect(Array.isArray(errorData)).toBe(true)
        })

        it('should list errors with custom date range', async () => {
            const dateFrom = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await listTool.handler(context, {
                dateFrom,
                dateTo,
                orderBy: OrderByErrors.Occurrences,
                orderDirection: OrderDirectionErrors.Descending,
            })
            const errorData = parseToolResponse(result)

            expect(Array.isArray(errorData)).toBe(true)
        })

        it('should filter by status', async () => {
            const result = await listTool.handler(context, {
                status: StatusErrors.Active,
            })
            const errorData = parseToolResponse(result)

            expect(Array.isArray(errorData)).toBe(true)
        })

        it('should handle empty results', async () => {
            const result = await listTool.handler(context, {
                dateFrom: new Date(Date.now() - 60000).toISOString(),
                dateTo: new Date(Date.now() - 30000).toISOString(),
            })
            const errorData = parseToolResponse(result)

            expect(Array.isArray(errorData)).toBe(true)
        })
    })

    describe('error-details tool', () => {
        const detailsTool = errorDetailsTool()

        it('should get error details by issue ID', async () => {
            const testIssueId = '00000000-0000-0000-0000-000000000000'

            const result = await detailsTool.handler(context, {
                issueId: testIssueId,
            })
            const errorDetails = parseToolResponse(result)

            expect(Array.isArray(errorDetails)).toBe(true)
        })

        it('should get error details with custom date range', async () => {
            const testIssueId = '00000000-0000-0000-0000-000000000000'
            const dateFrom = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await detailsTool.handler(context, {
                issueId: testIssueId,
                dateFrom,
                dateTo,
            })
            const errorDetails = parseToolResponse(result)

            expect(Array.isArray(errorDetails)).toBe(true)
        })
    })

    describe('Error tracking workflow', () => {
        it('should support listing errors and getting details workflow', async () => {
            const listTool = listErrorsTool()
            const detailsTool = errorDetailsTool()

            const listResult = await listTool.handler(context, {})
            const errorList = parseToolResponse(listResult)

            expect(Array.isArray(errorList)).toBe(true)

            if (errorList.length > 0 && errorList[0].issueId) {
                const firstError = errorList[0]
                const detailsResult = await detailsTool.handler(context, {
                    issueId: firstError.issueId,
                })
                const errorDetails = parseToolResponse(detailsResult)

                expect(Array.isArray(errorDetails)).toBe(true)
            } else {
                const testIssueId = '00000000-0000-0000-0000-000000000000'
                const detailsResult = await detailsTool.handler(context, {
                    issueId: testIssueId,
                })
                const errorDetails = parseToolResponse(detailsResult)

                expect(Array.isArray(errorDetails)).toBe(true)
            }
        })
    })
})
