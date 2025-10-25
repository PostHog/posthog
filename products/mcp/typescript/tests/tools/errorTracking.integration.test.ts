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
import updateIssueTool from '@/tools/errorTracking/updateIssue'
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

    describe('update-issue tool', () => {
        const updateTool = updateIssueTool()
        const listTool = listErrorsTool()

        it('should update issue status', async () => {
            const listResult = await listTool.handler(context, {
                status: StatusErrors.Active,
            })
            const errorList = parseToolResponse(listResult)

            if (errorList.length > 0 && errorList[0].issueId) {
                const issueId = errorList[0].issueId
                const originalStatus = errorList[0].status

                const updateResult = await updateTool.handler(context, {
                    issueId,
                    status: StatusErrors.Resolved,
                })

                expect(updateResult.content).toBeDefined()
                expect(updateResult.content[0].text).toContain('Successfully updated issue')

                await updateTool.handler(context, {
                    issueId,
                    status: originalStatus,
                })
            } else {
                console.log('Skipping test: No active errors found')
            }
        })

        it('should update issue name', async () => {
            const listResult = await listTool.handler(context, {})
            const errorList = parseToolResponse(listResult)

            if (errorList.length > 0 && errorList[0].issueId) {
                const issueId = errorList[0].issueId
                const originalName = errorList[0].name

                const newName = `Test Updated Name ${Date.now()}`
                const updateResult = await updateTool.handler(context, {
                    issueId,
                    name: newName,
                })

                expect(updateResult.content).toBeDefined()
                expect(updateResult.content[0].text).toContain('Successfully updated issue')

                await updateTool.handler(context, {
                    issueId,
                    name: originalName,
                })
            } else {
                console.log('Skipping test: No errors found')
            }
        })

        it('should update both status and name', async () => {
            const listResult = await listTool.handler(context, {})
            const errorList = parseToolResponse(listResult)

            if (errorList.length > 0 && errorList[0].issueId) {
                const issueId = errorList[0].issueId
                const originalStatus = errorList[0].status
                const originalName = errorList[0].name

                const newName = `Test Combined Update ${Date.now()}`
                const updateResult = await updateTool.handler(context, {
                    issueId,
                    status: StatusErrors.Suppressed,
                    name: newName,
                })

                expect(updateResult.content).toBeDefined()
                expect(updateResult.content[0].text).toContain('Successfully updated issue')

                await updateTool.handler(context, {
                    issueId,
                    status: originalStatus,
                    name: originalName,
                })
            } else {
                console.log('Skipping test: No errors found')
            }
        })

        it('should handle invalid issue ID', async () => {
            const invalidIssueId = '00000000-0000-0000-0000-000000000001'

            await expect(
                updateTool.handler(context, {
                    issueId: invalidIssueId,
                    status: StatusErrors.Resolved,
                })
            ).rejects.toThrow()
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
