import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import { PostHogApiError } from '@/lib/errors'
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

type ErrorTrackingSymbolSetListResult = {
    count?: number
    results?: Array<{ id?: string | null; ref?: string | null; has_uploaded_file?: boolean | null }>
}

describe('Error Tracking', { concurrent: false }, () => {
    let context: Context
    let currentUserId: number
    const issuesListTool = GENERATED_TOOLS['query-error-tracking-issues-list']!()
    const issueTool = GENERATED_TOOLS['query-error-tracking-issue']!()
    const issueEventsTool = GENERATED_TOOLS['query-error-tracking-issue-events']!()
    const createdAssignmentRuleIds: string[] = []
    const createdGroupingRuleIds: string[] = []
    const createdSuppressionRuleIds: string[] = []
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
        for (const id of createdSuppressionRuleIds) {
            try {
                await context.api.request({
                    method: 'DELETE',
                    path: `/api/environments/${TEST_PROJECT_ID}/error_tracking/suppression_rules/${id}/`,
                })
            } catch {
                // best effort — rule may already be deleted
            }
        }
        createdSuppressionRuleIds.length = 0
        await cleanupResources(context.api, TEST_PROJECT_ID!, createdResources)
    })

    async function getIssueIds(limit: number = 2): Promise<string[]> {
        const result = await issuesListTool.handler(context, { status: 'all', limit })
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

    // The issues list reads the denormalized ClickHouse table, which lags Postgres deletes
    // (issue merges) by a few seconds — re-list until the first listed issue resolves.
    async function waitForFirstLiveIssueDetails(
        listParams: Parameters<typeof issuesListTool.handler>[1] = {}
    ): Promise<{ issueId: string; details: { id?: string | null } } | undefined> {
        const deadline = Date.now() + 10_000
        while (true) {
            const listResult = await issuesListTool.handler(context, listParams)
            const errorList = parseToolResponse(listResult) as ErrorTrackingIssueListResult
            const issueId = (errorList.results ?? [])
                .map((issue) => issue.id)
                .find((id): id is string => typeof id === 'string')
            if (!issueId) {
                return undefined
            }

            try {
                const detailsResult = await issueTool.handler(context, { issueId, volumeResolution: 0 })
                return { issueId, details: parseToolResponse(detailsResult) }
            } catch (error) {
                if (!(error instanceof PostHogApiError) || error.status !== 404 || Date.now() >= deadline) {
                    throw error
                }
            }
            await new Promise((resolve) => setTimeout(resolve, 1000))
        }
    }

    describe('query-error-tracking-issues-list tool', () => {
        it('should list errors with default parameters', async () => {
            const result = await issuesListTool.handler(context, {})
            const errorData = parseToolResponse(result)

            expect(Array.isArray(errorData.results)).toBe(true)
        })

        it('should list errors with custom date range', async () => {
            const dateFrom = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await issuesListTool.handler(context, {
                dateRange: { date_from: dateFrom, date_to: dateTo },
                orderBy: 'occurrences',
                orderDirection: 'DESC',
            })
            const errorData = parseToolResponse(result)

            expect(Array.isArray(errorData.results)).toBe(true)
        })

        it('should filter by status', async () => {
            const result = await issuesListTool.handler(context, {
                status: 'active',
            })
            const errorData = parseToolResponse(result)

            expect(Array.isArray(errorData.results)).toBe(true)
        })

        it('should handle empty results', async () => {
            const result = await issuesListTool.handler(context, {
                dateRange: {
                    date_from: new Date(Date.now() - 60000).toISOString(),
                    date_to: new Date(Date.now() - 30000).toISOString(),
                },
            })
            const errorData = parseToolResponse(result)

            expect(Array.isArray(errorData.results)).toBe(true)
        })

        it('should get error details by issue ID when data exists', async () => {
            const issueId = await getFirstIssueId()
            if (!issueId) {
                return
            }

            const result = await issueTool.handler(context, {
                issueId,
                volumeResolution: 0,
            })
            const errorDetails = parseToolResponse(result)

            expect(errorDetails.id).toBe(issueId)
        })

        it('should get issue events when data exists', async () => {
            const issueId = await getFirstIssueId()
            if (!issueId) {
                return
            }

            const result = await issueEventsTool.handler(context, {
                issueId,
                limit: 1,
            })
            const eventData = parseToolResponse(result)

            expect(Array.isArray(eventData.results)).toBe(true)
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
                                    key: '$exception_types',
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
                                    key: '$exception_types',
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
            })) as {
                id: string
                filters: unknown
                assignee: { type: string; id: number | string } | null
                description?: string | null
            }

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

    describe('suppression-rules create tool', () => {
        const suppressionRulesCreateTool = GENERATED_TOOLS['error-tracking-suppression-rules-create']!()

        it('should create a suppression rule', async () => {
            const result = (await suppressionRulesCreateTool.handler(context, {
                filters: {
                    type: 'AND',
                    values: [
                        {
                            type: 'AND',
                            values: [
                                {
                                    key: '$exception_types',
                                    type: 'event',
                                    value: ['TypeError'],
                                    operator: 'exact',
                                },
                            ],
                        },
                    ],
                },
                sampling_rate: 0.25,
            })) as { id: string; filters: unknown; sampling_rate?: number }

            createdSuppressionRuleIds.push(result.id)

            expect(result).toBeTruthy()
            expect(typeof result.id).toBe('string')
            expect(result.filters).toBeTruthy()
            expect(result.sampling_rate).toBe(0.25)
        })
    })

    describe('settings tools', () => {
        const settingsGetTool = GENERATED_TOOLS['error-tracking-settings-get']!()
        const settingsUpdateTool = GENERATED_TOOLS['error-tracking-settings-update']!()

        type ErrorTrackingSettingsResult = {
            project_rate_limit_value?: number | null
            project_rate_limit_bucket_size_minutes?: number | null
            per_issue_rate_limit_value?: number | null
            per_issue_rate_limit_bucket_size_minutes?: number | null
        }

        // Settings are a single per-team row, so snapshot the originals and restore them after each test
        // to keep the shared project's rate limits untouched.
        let originalSettings: ErrorTrackingSettingsResult

        beforeAll(async () => {
            originalSettings = (await settingsGetTool.handler(context, {})) as ErrorTrackingSettingsResult
        })

        afterEach(async () => {
            await settingsUpdateTool.handler(context, {
                project_rate_limit_value: originalSettings.project_rate_limit_value ?? null,
                project_rate_limit_bucket_size_minutes: originalSettings.project_rate_limit_bucket_size_minutes ?? null,
                per_issue_rate_limit_value: originalSettings.per_issue_rate_limit_value ?? null,
                per_issue_rate_limit_bucket_size_minutes:
                    originalSettings.per_issue_rate_limit_bucket_size_minutes ?? null,
            })
        })

        it('should get the current settings', async () => {
            const result = (await settingsGetTool.handler(context, {})) as ErrorTrackingSettingsResult

            expect(result).toBeTruthy()
            expect('project_rate_limit_value' in result).toBe(true)
            expect('per_issue_rate_limit_value' in result).toBe(true)
        })

        it('should update the project and per-issue rate limits', async () => {
            const result = (await settingsUpdateTool.handler(context, {
                project_rate_limit_value: 5000,
                project_rate_limit_bucket_size_minutes: 60,
                per_issue_rate_limit_value: 100,
                per_issue_rate_limit_bucket_size_minutes: 15,
            })) as ErrorTrackingSettingsResult

            expect(result.project_rate_limit_value).toBe(5000)
            expect(result.project_rate_limit_bucket_size_minutes).toBe(60)
            expect(result.per_issue_rate_limit_value).toBe(100)
            expect(result.per_issue_rate_limit_bucket_size_minutes).toBe(15)
        })

        it('should clear a rate limit when set to null', async () => {
            await settingsUpdateTool.handler(context, { project_rate_limit_value: 1000 })

            const result = (await settingsUpdateTool.handler(context, {
                project_rate_limit_value: null,
            })) as ErrorTrackingSettingsResult

            expect(result.project_rate_limit_value).toBeNull()
        })

        it('should only update the fields provided', async () => {
            await settingsUpdateTool.handler(context, {
                project_rate_limit_value: 2000,
                per_issue_rate_limit_value: 50,
            })

            const result = (await settingsUpdateTool.handler(context, {
                per_issue_rate_limit_value: 75,
            })) as ErrorTrackingSettingsResult

            expect(result.per_issue_rate_limit_value).toBe(75)
            expect(result.project_rate_limit_value).toBe(2000)
        })
    })

    describe('symbol-sets list tool', () => {
        const symbolSetsListTool = GENERATED_TOOLS['error-tracking-symbol-sets-list']!()

        it('should list symbol sets', async () => {
            const result = (await symbolSetsListTool.handler(context, { limit: 5 })) as ErrorTrackingSymbolSetListResult

            expect(result).toBeTruthy()
            expect(typeof result.count).toBe('number')
            expect(Array.isArray(result.results)).toBe(true)
        })
    })

    describe('symbol-sets retrieve tool', () => {
        const symbolSetsListTool = GENERATED_TOOLS['error-tracking-symbol-sets-list']!()
        const symbolSetRetrieveTool = GENERATED_TOOLS['error-tracking-symbol-sets-retrieve']!()

        it('should retrieve a symbol set by ID when one exists', async () => {
            const listResult = (await symbolSetsListTool.handler(context, {
                limit: 1,
            })) as ErrorTrackingSymbolSetListResult
            const symbolSet = listResult.results?.find(
                (item): item is { id: string; ref?: string | null } => typeof item.id === 'string'
            )
            if (!symbolSet) {
                return
            }

            if (symbolSet.ref) {
                const filteredResult = (await symbolSetsListTool.handler(context, {
                    ref: symbolSet.ref,
                    limit: 1,
                })) as ErrorTrackingSymbolSetListResult
                expect(filteredResult.results?.some((item) => item.id === symbolSet.id)).toBe(true)
            }

            const result = (await symbolSetRetrieveTool.handler(context, { id: symbolSet.id })) as {
                id?: string
                ref?: string
            }

            expect(result).toBeTruthy()
            expect(result.id).toBe(symbolSet.id)
        })
    })

    describe('symbol-sets download tool', () => {
        const symbolSetsListTool = GENERATED_TOOLS['error-tracking-symbol-sets-list']!()
        const symbolSetDownloadTool = GENERATED_TOOLS['error-tracking-symbol-sets-download-retrieve']!()

        it('should get a download URL by ID when an uploaded symbol set exists', async () => {
            const listResult = (await symbolSetsListTool.handler(context, {
                status: 'valid',
                limit: 1,
            })) as ErrorTrackingSymbolSetListResult
            const symbolSet = listResult.results?.find((item): item is { id: string } => typeof item.id === 'string')
            if (!symbolSet) {
                return
            }

            const result = (await symbolSetDownloadTool.handler(context, { id: symbolSet.id })) as { url?: string }

            expect(result).toBeTruthy()
            expect(typeof result.url).toBe('string')
            expect(result.url?.length).toBeGreaterThan(0)
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
            const live = await waitForFirstLiveIssueDetails()

            if (live) {
                expect(live.details.id).toBe(live.issueId)
            }
        })

        it('should support full error tracking workflow: list, get details, and update status', async () => {
            const updateTool = GENERATED_TOOLS['error-tracking-issues-partial-update']!()

            const live = await waitForFirstLiveIssueDetails({ status: 'all' })

            if (!live) {
                return
            }

            const { issueId } = live
            expect(live.details.id).toBe(issueId)

            const updateResult = (await updateTool.handler(context, {
                id: issueId,
                status: 'resolved',
            })) as { status: string }
            expect(updateResult).toBeTruthy()
            expect(updateResult.status).toBe('resolved')
        })
    })
})
