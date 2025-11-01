import { MOCK_TEAM_ID } from 'lib/api.mock'

import { combineUrl, router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { addProjectIdIfMissing } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'

import { NodeKind, TracesQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType } from '~/types'

import { llmAnalyticsSessionLogic } from './llmAnalyticsSessionLogic'

describe('llmAnalyticsSessionLogic', () => {
    let logic: ReturnType<typeof llmAnalyticsSessionLogic.build>

    beforeEach(async () => {
        initKeaTests()
        logic = llmAnalyticsSessionLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('URL routing', () => {
        it('properly loads session scene with basic session ID', async () => {
            const sessionId = 'session-123'
            const sessionUrl = combineUrl(urls.llmAnalyticsSession(sessionId))
            const finalUrl = addProjectIdIfMissing(sessionUrl.url, MOCK_TEAM_ID)

            router.actions.push(finalUrl)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.sessionId).toBe(sessionId)
        })

        it('properly loads session scene when session ID contains a colon', async () => {
            const sessionIdWithColon = 'session:group:16-16:81008d53ff0a708b'
            const sessionUrl = combineUrl(urls.llmAnalyticsSession(sessionIdWithColon))
            const finalUrl = addProjectIdIfMissing(sessionUrl.url, MOCK_TEAM_ID)

            router.actions.push(finalUrl)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.sessionId).toBe(sessionIdWithColon)
        })

        it('properly loads session scene when session ID contains multiple colons', async () => {
            const sessionIdWithMultipleColons = 'namespace:session:12345:abcdef:xyz'
            const sessionUrl = combineUrl(urls.llmAnalyticsSession(sessionIdWithMultipleColons))

            router.actions.push(addProjectIdIfMissing(sessionUrl.url, MOCK_TEAM_ID))
            await expectLogic(logic).toMatchValues({
                sessionId: sessionIdWithMultipleColons,
            })
        })

        it('handles session ID with timestamp parameter', async () => {
            const sessionId = 'session-456'
            const timestamp = '2024-01-01T00:00:00Z'
            const sessionUrl = combineUrl(urls.llmAnalyticsSession(sessionId, { timestamp }))

            router.actions.push(addProjectIdIfMissing(sessionUrl.url, MOCK_TEAM_ID))
            await expectLogic(logic).toMatchValues({
                sessionId: sessionId,
                dateRange: { dateFrom: timestamp, dateTo: null },
            })
        })

        it('handles session ID with UUID format', async () => {
            const sessionId = '550e8400-e29b-41d4-a716-446655440000'
            const sessionUrl = combineUrl(urls.llmAnalyticsSession(sessionId))

            router.actions.push(addProjectIdIfMissing(sessionUrl.url, MOCK_TEAM_ID))
            await expectLogic(logic).toMatchValues({
                sessionId: sessionId,
            })
        })
    })

    describe('state management', () => {
        it('has correct initial state', () => {
            expect(logic.values.sessionId).toBe('')
            expect(logic.values.dateRange).toBeNull()
        })

        it('sets session ID via action', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSessionId('test-session-789')
            }).toMatchValues({
                sessionId: 'test-session-789',
            })
        })

        it('sets date range via action', async () => {
            await expectLogic(logic, () => {
                logic.actions.setDateRange('2024-01-01T00:00:00Z', '2024-01-31T23:59:59Z')
            }).toMatchValues({
                dateRange: {
                    dateFrom: '2024-01-01T00:00:00Z',
                    dateTo: '2024-01-31T23:59:59Z',
                },
            })
        })

        it('handles null date range values', async () => {
            await expectLogic(logic, () => {
                logic.actions.setDateRange(null, null)
            }).toMatchValues({
                dateRange: {
                    dateFrom: null,
                    dateTo: null,
                },
            })
        })

        it('handles partial date range (only dateFrom)', async () => {
            await expectLogic(logic, () => {
                logic.actions.setDateRange('2024-01-01T00:00:00Z')
            }).toMatchValues({
                dateRange: {
                    dateFrom: '2024-01-01T00:00:00Z',
                    dateTo: null,
                },
            })
        })
    })

    describe('query selector', () => {
        it('generates correct TracesQuery with session ID filter', async () => {
            logic.actions.setSessionId('test-session-123')
            await expectLogic(logic).toFinishAllListeners()

            const query = logic.values.query
            const source = query.source as TracesQuery

            expect(query.kind).toBe(NodeKind.DataTableNode)
            expect(source.kind).toBe(NodeKind.TracesQuery)
            expect(source.properties).toHaveLength(1)
            expect(source.properties![0]).toEqual({
                type: PropertyFilterType.Event,
                key: '$ai_session_id',
                operator: 'exact',
                value: 'test-session-123',
            })
        })

        it('includes date range in query when dateRange is set', async () => {
            logic.actions.setSessionId('test-session-456')
            logic.actions.setDateRange('2024-01-01T00:00:00Z', '2024-01-31T23:59:59Z')
            await expectLogic(logic).toFinishAllListeners()

            const query = logic.values.query
            const source = query.source as TracesQuery

            expect(source.dateRange).toEqual({
                date_from: '2024-01-01T00:00:00Z',
                date_to: '2024-01-31T23:59:59Z',
            })
        })

        it('generates default date range when dateRange has dateFrom but no dateTo', async () => {
            logic.actions.setSessionId('test-session-789')
            logic.actions.setDateRange('2024-01-01T00:00:00Z')
            await expectLogic(logic).toFinishAllListeners()

            const query = logic.values.query
            const source = query.source as TracesQuery

            expect(source.dateRange?.date_from).toBe('2024-01-01T00:00:00Z')
            expect(source.dateRange?.date_to).toBeTruthy()
            // date_to should be 30 days after date_from
            expect(new Date(source.dateRange!.date_to!).getTime()).toBeGreaterThan(
                new Date('2024-01-01T00:00:00Z').getTime()
            )
        })

        it('generates query with fallback date when no dateRange is set', async () => {
            logic.actions.setSessionId('test-session-no-dates')
            await expectLogic(logic).toFinishAllListeners()

            const query = logic.values.query
            const source = query.source as TracesQuery

            expect(source.dateRange?.date_from).toBeTruthy()
            // Should have a default starting date
        })

        it('updates query when session ID changes', async () => {
            logic.actions.setSessionId('session-1')
            await expectLogic(logic).toFinishAllListeners()

            let query = logic.values.query
            let source = query.source as TracesQuery
            expect(source.properties![0].value).toBe('session-1')

            logic.actions.setSessionId('session-2')
            await expectLogic(logic).toFinishAllListeners()

            query = logic.values.query
            source = query.source as TracesQuery
            expect(source.properties![0].value).toBe('session-2')
        })
    })

    describe('breadcrumbs selector', () => {
        it('generates correct breadcrumbs structure', async () => {
            logic.actions.setSessionId('test-session-breadcrumbs')
            await expectLogic(logic).toFinishAllListeners()

            const breadcrumbs = logic.values.breadcrumbs

            expect(breadcrumbs).toHaveLength(3)
            expect(breadcrumbs[0]).toEqual({
                key: 'LLMAnalytics',
                name: 'LLM analytics',
                path: urls.llmAnalyticsDashboard(),
                iconType: 'llm_analytics',
            })
            expect(breadcrumbs[1]).toEqual({
                key: 'LLMAnalyticsSessions',
                name: 'Sessions',
                path: urls.llmAnalyticsSessions(),
                iconType: 'llm_analytics',
            })
            expect(breadcrumbs[2]).toEqual({
                key: ['LLMAnalyticsSession', 'test-session-breadcrumbs'],
                name: 'test-session-breadcrumbs',
                iconType: 'llm_analytics',
            })
        })

        it('updates breadcrumbs when session ID changes', async () => {
            logic.actions.setSessionId('session-1')
            await expectLogic(logic).toFinishAllListeners()

            let breadcrumbs = logic.values.breadcrumbs
            expect(breadcrumbs[2].name).toBe('session-1')

            logic.actions.setSessionId('session-2')
            await expectLogic(logic).toFinishAllListeners()

            breadcrumbs = logic.values.breadcrumbs
            expect(breadcrumbs[2].name).toBe('session-2')
        })

        it('handles empty session ID in breadcrumbs', async () => {
            logic.actions.setSessionId('')
            await expectLogic(logic).toFinishAllListeners()

            const breadcrumbs = logic.values.breadcrumbs
            expect(breadcrumbs[2]).toEqual({
                key: ['LLMAnalyticsSession', ''],
                name: '',
                iconType: 'llm_analytics',
            })
        })
    })

    describe('integration with URL', () => {
        it('extracts both session ID and timestamp from URL', async () => {
            const sessionId = 'full-integration-test'
            const timestamp = '2024-06-15T12:00:00Z'
            const sessionUrl = combineUrl(urls.llmAnalyticsSession(sessionId, { timestamp }))

            router.actions.push(addProjectIdIfMissing(sessionUrl.url, MOCK_TEAM_ID))
            await expectLogic(logic).toMatchValues({
                sessionId: sessionId,
                dateRange: {
                    dateFrom: timestamp,
                    dateTo: null,
                },
            })

            // Query should reflect both values
            const query = logic.values.query
            const source = query.source as TracesQuery
            expect(source.properties![0].value).toBe(sessionId)
            expect(source.dateRange?.date_from).toBe(timestamp)
        })

        it('handles URL navigation without timestamp', async () => {
            const sessionId = 'no-timestamp-test'
            const sessionUrl = combineUrl(urls.llmAnalyticsSession(sessionId))

            router.actions.push(addProjectIdIfMissing(sessionUrl.url, MOCK_TEAM_ID))
            await expectLogic(logic).toMatchValues({
                sessionId: sessionId,
                dateRange: null,
            })
        })
    })
})
