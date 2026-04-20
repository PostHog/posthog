import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    type CreatedResources,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    cleanupResources,
    createTestClient,
    createTestContext,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/error_tracking'
import type { Context } from '@/tools/types'

type ErrorTrackingIssueListResult = {
    results?: Array<{ id?: string | null }>
}

type ErrorTrackingFingerprintListResult = {
    results?: Array<{ fingerprint?: string | null }>
}

describe('Error Tracking', { concurrent: false }, () => {
    let context: Context
    let currentUserId: number
    const queryTool = GENERATED_TOOLS['query-error-tracking-issues']!()
    const createdAssignmentRuleIds: string[] = []
    const createdGroupingRuleIds: string[] = []
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
        const user = await context.api.request<{ id: number }>({
            method: 'GET',
            path: '/api/users/@me/',
        })
        currentUserId = user.id
    })

    afterEach(async () => {
        for (const id of createdAssignmentRuleIds) {
            try {
                await context.api.request({
                    method: 'DELETE',
                    path: `/api/environments/${TEST_PROJECT_ID}/error_tracking/assignment_rules/${id}/`,
                })
            } catch {
                // best effort — rule may already be deleted
            }
        }
        createdAssignmentRuleIds.length = 0
        for (const id of createdGroupingRuleIds) {
            try {
                await context.api.request({
                    method: 'DELETE',
                    path: `/api/environments/${TEST_PROJECT_ID}/error_tracking/grouping_rules/${id}/`,
                })
            } catch {
                // best effort — rule may already be deleted
            }
        }
        createdGroupingRuleIds.length = 0
        await cleanupResources(context.api, TEST_PROJECT_ID!, createdResources)
    })

    async function getIssueIds(limit: number = 2): Promise<string[]> {
        const result = await queryTool.handler(context, { status: 'all', limit })
        const errors = parseToolResponse(result) as ErrorTrackingIssueListResult

        if (!Array.isArray(errors.results)) {
            return []
        }

        return [
            ...new Set(
                errors.results
                    .map((issue: { id?: string | null }) => issue.id)
                    .filter((id: string | null | undefined): id is string => typeof id === 'string')
            ),
        ]
    }

    async function getFirstIssueId(): Promise<string | undefined> {
        const [issueId] = await getIssueIds(1)
        return issueId
    }

    async function getIssueFingerprints(issueId: string): Promise<string[]> {
        const result = await context.api.request<ErrorTrackingFingerprintListResult>({
            method: 'GET',
            path: `/api/environments/${TEST_PROJECT_ID}/error_tracking/fingerprints/`,
            query: { issue_id: issueId },
        })

        if (!Array.isArray(result.results)) {
            return []
        }

        return result.results
            .map((fingerprint: { fingerprint?: string | null }) => fingerprint.fingerprint)
            .filter((fingerprint: string | null | undefined): fingerprint is string => typeof fingerprint === 'string')
    }

    describe('query-error-tracking-issues tool', () => {
        it('should list errors with default parameters', async () => {
            const result = await queryTool.handler(context, {})
            const errorData = parseToolResponse(result)

            expect(Array.isArray(errorData.results)).toBe(true)
        })

        it('should list errors with custom date range', async () => {
            const dateFrom = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await queryTool.handler(context, {
                dateRange: { date_from: dateFrom, date_to: dateTo },
                orderBy: 'occurrences',
                orderDirection: 'DESC',
            })
            const errorData = parseToolResponse(result)

            expect(Array.isArray(errorData.results)).toBe(true)
        })

        it('should filter by status', async () => {
            const result = await queryTool.handler(context, {
                status: 'active',
            })
            const errorData = parseToolResponse(result)

            expect(Array.isArray(errorData.results)).toBe(true)
        })

        it('should handle empty results', async () => {
            const result = await queryTool.handler(context, {
                dateRange: {
                    date_from: new Date(Date.now() - 60000).toISOString(),
                    date_to: new Date(Date.now() - 30000).toISOString(),
                },
            })
            const errorData = parseToolResponse(result)

            expect(Array.isArray(errorData.results)).toBe(true)
        })

        it('should get error details by issue ID', async () => {
            const testIssueId = '00000000-0000-0000-0000-000000000000'

            const result = await queryTool.handler(context, {
                issueId: testIssueId,
                volumeResolution: 0,
            })
            const errorDetails = parseToolResponse(result)

            expect(Array.isArray(errorDetails.results)).toBe(true)
        })

        it('should get error details with custom date range', async () => {
            const testIssueId = '00000000-0000-0000-0000-000000000000'
            const dateFrom = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await queryTool.handler(context, {
                issueId: testIssueId,
                volumeResolution: 0,
                dateRange: { date_from: dateFrom, date_to: dateTo },
            })
            const errorDetails = parseToolResponse(result)

            expect(Array.isArray(errorDetails.results)).toBe(true)
        })
    })

    describe('assignment-rules list tool', () => {
        const assignmentRulesListTool = GENERATED_TOOLS['error-tracking-assignment-rules-list']!()

        it('should list assignment rules', async () => {
            const result = (await assignmentRulesListTool.handler(context, {})) as {
                count: number
                results: unknown[]
            }

            expect(result).toBeTruthy()
            expect(typeof result.count).toBe('number')
            expect(Array.isArray(result.results)).toBe(true)
        })
    })

    describe('assignment-rules create tool', () => {
        const assignmentRulesCreateTool = GENERATED_TOOLS['error-tracking-assignment-rules-create']!()

        it('should create an assignment rule', async () => {
            const result = (await assignmentRulesCreateTool.handler(context, {
                filters: {
                    type: 'AND',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                {
                                    key: '$exception_type',
                                    type: 'event',
                                    value: ['TypeError'],
                                    operator: 'exact',
                                },
                            ],
                        },
                    ],
                },
                assignee: { type: 'user', id: currentUserId },
            })) as { id: string; filters: unknown; assignee: { type: string; id: number | string } | null }

            createdAssignmentRuleIds.push(result.id)

            expect(result).toBeTruthy()
            expect(typeof result.id).toBe('string')
            expect(result.filters).toBeTruthy()
            expect(result.assignee).toEqual({ type: 'user', id: currentUserId })
        })
    })

    describe('grouping-rules list tool', () => {
        const groupingRulesListTool = GENERATED_TOOLS['error-tracking-grouping-rules-list']!()

        it('should list grouping rules', async () => {
            const result = (await groupingRulesListTool.handler(context, {})) as {
                results: unknown[]
            }

            expect(result).toBeTruthy()
            expect(Array.isArray(result.results)).toBe(true)
        })
    })

    describe('grouping-rules create tool', () => {
        const groupingRulesCreateTool = GENERATED_TOOLS['error-tracking-grouping-rules-create']!()

        it('should create a grouping rule', async () => {
            const result = (await groupingRulesCreateTool.handler(context, {
                filters: {
                    type: 'AND',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                {
                                    key: '$exception_type',
                                    type: 'event',
                                    value: ['TypeError'],
                                    operator: 'exact',
                                },
                            ],
                        },
                    ],
                },
                assignee: { type: 'user', id: currentUserId },
                description: 'Group TypeErrors from MCP integration test',
            })) as { id: string; filters: unknown; assignee: { type: string; id: number | string } | null; description?: string | null }

            createdGroupingRuleIds.push(result.id)

            expect(result).toBeTruthy()
            expect(typeof result.id).toBe('string')
            expect(result.filters).toBeTruthy()
            expect(result.assignee).toEqual({ type: 'user', id: currentUserId })
            expect(result.description).toBe('Group TypeErrors from MCP integration test')
        })
    })

    describe('suppression-rules list tool', () => {
        const suppressionRulesListTool = GENERATED_TOOLS['error-tracking-suppression-rules-list']!()

        it('should list suppression rules', async () => {
            const result = (await suppressionRulesListTool.handler(context, {})) as {
                count: number
                results: unknown[]
            }

            expect(result).toBeTruthy()
            expect(typeof result.count).toBe('number')
            expect(Array.isArray(result.results)).toBe(true)
        })
    })

    describe('update-issue-status tool', () => {
        const updateTool = GENERATED_TOOLS['error-tracking-issues-partial-update']!()

        it('should update issue status to resolved', async () => {
            const issueId = await getFirstIssueId()
            if (!issueId) {
                return
            }

            const result = (await updateTool.handler(context, {
                id: issueId,
                status: 'resolved',
            })) as { status: string }

            expect(result).toBeTruthy()
            expect(result.status).toBe('resolved')
        })

        it('should update issue status back to active', async () => {
            const issueId = await getFirstIssueId()
            if (!issueId) {
                return
            }

            const result = (await updateTool.handler(context, {
                id: issueId,
                status: 'active',
            })) as { status: string }

            expect(result).toBeTruthy()
            expect(result.status).toBe('active')
        })
    })

    describe('merge-issues tool', () => {
        const mergeTool = GENERATED_TOOLS['error-tracking-issues-merge-create']!()

        it('should merge issues into the selected target issue', async () => {
            const [targetIssueId, sourceIssueId] = await getIssueIds(2)
            if (!targetIssueId || !sourceIssueId) {
                return
            }

            const result = (await mergeTool.handler(context, {
                id: targetIssueId,
                ids: [sourceIssueId],
            })) as { success: boolean }

            expect(result).toBeTruthy()
            expect(result.success).toBe(true)
        })
    })

    describe('split-issue tool', () => {
        const splitTool = GENERATED_TOOLS['error-tracking-issues-split-create']!()

        it('should split a fingerprint into a new issue', async () => {
            for (const issueId of await getIssueIds(10)) {
                const [fingerprint] = await getIssueFingerprints(issueId)
                if (!fingerprint) {
                    continue
                }

                const result = (await splitTool.handler(context, {
                    id: issueId,
                    fingerprints: [{ fingerprint, name: 'Split from MCP integration test' }],
                })) as { success: boolean; new_issue_ids: string[] }

                expect(result).toBeTruthy()
                expect(result.success).toBe(true)
                expect(Array.isArray(result.new_issue_ids)).toBe(true)
                expect(result.new_issue_ids.length).toBeGreaterThan(0)
                return
            }

            throw new Error(
                'Split integration test requires at least one error tracking issue with an associated fingerprint in the shared test project.'
            )
        })
    })

    describe('Error tracking workflow', () => {
        it('should support listing errors and getting details workflow', async () => {
            const queryTool = GENERATED_TOOLS['query-error-tracking-issues']!()

            const listResult = await queryTool.handler(context, {})
            const errorList = parseToolResponse(listResult)

            expect(Array.isArray(errorList.results)).toBe(true)

            if (errorList.results.length > 0 && errorList.results[0].issueId) {
                const firstError = errorList.results[0]
                const detailsResult = await queryTool.handler(context, {
                    issueId: firstError.issueId,
                    volumeResolution: 0,
                })
                const errorDetails = parseToolResponse(detailsResult)

                expect(Array.isArray(errorDetails.results)).toBe(true)
            } else {
                const testIssueId = '00000000-0000-0000-0000-000000000000'
                const detailsResult = await queryTool.handler(context, {
                    issueId: testIssueId,
                    volumeResolution: 0,
                })
                const errorDetails = parseToolResponse(detailsResult)

                expect(Array.isArray(errorDetails.results)).toBe(true)
            }
        })

        it('should support full error tracking workflow: list, get details, and update status', async () => {
            const queryTool = GENERATED_TOOLS['query-error-tracking-issues']!()
            const updateTool = GENERATED_TOOLS['error-tracking-issues-partial-update']!()

            const listResult = await queryTool.handler(context, { status: 'all' })
            const errorList = parseToolResponse(listResult)

            expect(Array.isArray(errorList.results)).toBe(true)

            if (errorList.results.length === 0 || !errorList.results[0].id) {
                return
            }

            const issueId = errorList.results[0].id

            const detailsResult = await queryTool.handler(context, {
                issueId,
                volumeResolution: 0,
            })
            const errorDetails = parseToolResponse(detailsResult)
            expect(Array.isArray(errorDetails.results)).toBe(true)

            const updateResult = (await updateTool.handler(context, {
                id: issueId,
                status: 'resolved',
            })) as { status: string }
            expect(updateResult).toBeTruthy()
            expect(updateResult.status).toBe('resolved')
        })
    })
})
