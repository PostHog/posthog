import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { sceneLogic } from '../../../frontend/src/scenes/sceneLogic'
import { llmAnalyticsSharedLogic } from './llmAnalyticsSharedLogic'
import { llmAnalyticsSessionsViewLogic } from './tabs/llmAnalyticsSessionsViewLogic'

describe('llmAnalyticsSharedLogic', () => {
    let logic: ReturnType<typeof llmAnalyticsSharedLogic.build>

    beforeEach(() => {
        initKeaTests()
        sceneLogic.mount()
        router.actions.push(urls.llmAnalyticsTraces())
        logic = llmAnalyticsSharedLogic({ tabId: sceneLogic.values.activeTabId || '' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('should handle URL parameters correctly', () => {
        const filters = [
            {
                type: 'event',
                key: 'browser',
                value: 'Chrome',
                operator: 'exact',
            },
        ]

        // Navigate with various parameters
        router.actions.push(urls.llmAnalyticsTraces(), {
            filters: filters,
            date_from: '-14d',
            date_to: '-1d',
            filter_test_accounts: 'true',
        })

        // Should apply all parameters
        expectLogic(logic).toMatchValues({
            propertyFilters: filters,
            dateFilter: {
                dateFrom: '-14d',
                dateTo: '-1d',
            },
            shouldFilterTestAccounts: true,
        })
    })

    it('should reset filters when switching tabs without params', () => {
        // Set some filters first
        logic.actions.setPropertyFilters([
            {
                type: PropertyFilterType.Event,
                key: 'test',
                value: 'value',
                operator: PropertyOperator.Exact,
            },
        ])
        logic.actions.setDates('-30d', '-1d')
        logic.actions.setShouldFilterTestAccounts(true)

        // Navigate to another tab without params
        router.actions.push(urls.llmAnalyticsGenerations())

        // Should reset to defaults
        expectLogic(logic).toMatchValues({
            propertyFilters: [],
            dateFilter: {
                dateFrom: '-1h',
                dateTo: null,
            },
            shouldFilterTestAccounts: false,
        })
    })
})

describe('llmAnalyticsSessionsViewLogic', () => {
    let sharedLogic: ReturnType<typeof llmAnalyticsSharedLogic.build>
    let sessionsLogic: ReturnType<typeof llmAnalyticsSessionsViewLogic.build>

    beforeEach(() => {
        initKeaTests()
        sceneLogic.mount()
        router.actions.push(urls.llmAnalyticsSessions())
        sharedLogic = llmAnalyticsSharedLogic({})
        sharedLogic.mount()
        sessionsLogic = llmAnalyticsSessionsViewLogic({})
        sessionsLogic.mount()
    })

    afterEach(() => {
        sessionsLogic.unmount()
        sharedLogic.unmount()
    })

    describe('session expansion state', () => {
        it('toggles session expansion state', async () => {
            await expectLogic(sessionsLogic, () => {
                sessionsLogic.actions.toggleSessionExpanded('session-123')
            }).toMatchValues({
                expandedSessionIds: new Set(['session-123']),
            })

            // Toggle again to collapse
            await expectLogic(sessionsLogic, () => {
                sessionsLogic.actions.toggleSessionExpanded('session-123')
            }).toMatchValues({
                expandedSessionIds: new Set(),
            })
        })

        it('handles multiple expanded sessions', async () => {
            await expectLogic(sessionsLogic, () => {
                sessionsLogic.actions.toggleSessionExpanded('session-1')
                sessionsLogic.actions.toggleSessionExpanded('session-2')
                sessionsLogic.actions.toggleSessionExpanded('session-3')
            }).toMatchValues({
                expandedSessionIds: new Set(['session-1', 'session-2', 'session-3']),
            })

            // Collapse middle session
            await expectLogic(sessionsLogic, () => {
                sessionsLogic.actions.toggleSessionExpanded('session-2')
            }).toMatchValues({
                expandedSessionIds: new Set(['session-1', 'session-3']),
            })
        })

        it('clears expanded sessions when date filter changes', async () => {
            sessionsLogic.actions.toggleSessionExpanded('session-123')

            await expectLogic(sessionsLogic, () => {
                sharedLogic.actions.setDates('-7d', null)
            }).toMatchValues({
                expandedSessionIds: new Set(),
                sessionTraces: {},
            })
        })

        it('clears expanded sessions when property filters change', async () => {
            sessionsLogic.actions.toggleSessionExpanded('session-456')

            await expectLogic(sessionsLogic, () => {
                sharedLogic.actions.setPropertyFilters([
                    {
                        type: PropertyFilterType.Event,
                        key: 'browser',
                        value: 'Chrome',
                        operator: PropertyOperator.Exact,
                    },
                ])
            }).toMatchValues({
                expandedSessionIds: new Set(),
                sessionTraces: {},
            })
        })

        it('clears expanded sessions when test accounts filter changes', async () => {
            sessionsLogic.actions.toggleSessionExpanded('session-789')

            await expectLogic(sessionsLogic, () => {
                sharedLogic.actions.setShouldFilterTestAccounts(true)
            }).toMatchValues({
                expandedSessionIds: new Set(),
                sessionTraces: {},
            })
        })
    })

    describe('trace expansion state', () => {
        it('toggles trace expansion state', async () => {
            await expectLogic(sessionsLogic, () => {
                sessionsLogic.actions.toggleTraceExpanded('trace-abc')
            }).toMatchValues({
                expandedTraceIds: new Set(['trace-abc']),
            })

            // Toggle again to collapse
            await expectLogic(sessionsLogic, () => {
                sessionsLogic.actions.toggleTraceExpanded('trace-abc')
            }).toMatchValues({
                expandedTraceIds: new Set(),
            })
        })

        it('handles multiple expanded traces', async () => {
            await expectLogic(sessionsLogic, () => {
                sessionsLogic.actions.toggleTraceExpanded('trace-1')
                sessionsLogic.actions.toggleTraceExpanded('trace-2')
            }).toMatchValues({
                expandedTraceIds: new Set(['trace-1', 'trace-2']),
            })
        })

        it('clears expanded traces when filters change', async () => {
            sessionsLogic.actions.toggleTraceExpanded('trace-xyz')

            await expectLogic(sessionsLogic, () => {
                sharedLogic.actions.setDates('-14d', null)
            }).toMatchValues({
                expandedTraceIds: new Set(),
                fullTraces: {},
            })
        })
    })

    describe('loading state tracking', () => {
        it('tracks loading state for session traces', async () => {
            sessionsLogic.actions.loadSessionTraces('session-123')

            expect(sessionsLogic.values.loadingSessionTraces.has('session-123')).toBe(true)

            sessionsLogic.actions.loadSessionTracesSuccess('session-123', [])

            expect(sessionsLogic.values.loadingSessionTraces.has('session-123')).toBe(false)
        })

        it('clears loading state on failure', async () => {
            sessionsLogic.actions.loadSessionTraces('session-456')

            expect(sessionsLogic.values.loadingSessionTraces.has('session-456')).toBe(true)

            sessionsLogic.actions.loadSessionTracesFailure('session-456', new Error('Test error'))

            expect(sessionsLogic.values.loadingSessionTraces.has('session-456')).toBe(false)
        })

        it('tracks loading state for full traces', async () => {
            sessionsLogic.actions.loadFullTrace('trace-abc')

            expect(sessionsLogic.values.loadingFullTraces.has('trace-abc')).toBe(true)

            const mockTrace = { id: 'trace-abc' } as any
            sessionsLogic.actions.loadFullTraceSuccess('trace-abc', mockTrace)

            expect(sessionsLogic.values.loadingFullTraces.has('trace-abc')).toBe(false)
        })

        it('handles multiple concurrent loading operations', async () => {
            sessionsLogic.actions.loadSessionTraces('session-1')
            sessionsLogic.actions.loadSessionTraces('session-2')
            sessionsLogic.actions.loadFullTrace('trace-1')

            expect(sessionsLogic.values.loadingSessionTraces.has('session-1')).toBe(true)
            expect(sessionsLogic.values.loadingSessionTraces.has('session-2')).toBe(true)
            expect(sessionsLogic.values.loadingFullTraces.has('trace-1')).toBe(true)

            sessionsLogic.actions.loadSessionTracesSuccess('session-1', [])

            expect(sessionsLogic.values.loadingSessionTraces.has('session-1')).toBe(false)
            expect(sessionsLogic.values.loadingSessionTraces.has('session-2')).toBe(true)
            expect(sessionsLogic.values.loadingFullTraces.has('trace-1')).toBe(true)
        })
    })

    describe('session traces data', () => {
        it('stores loaded session traces', async () => {
            const mockTraces = [{ id: 'trace-1' }, { id: 'trace-2' }] as any[]

            await expectLogic(sessionsLogic, () => {
                sessionsLogic.actions.loadSessionTracesSuccess('session-123', mockTraces)
            }).toMatchValues({
                sessionTraces: {
                    'session-123': mockTraces,
                },
            })
        })

        it('stores traces for multiple sessions', async () => {
            const mockTraces1 = [{ id: 'trace-1' }] as any[]
            const mockTraces2 = [{ id: 'trace-2' }] as any[]

            sessionsLogic.actions.loadSessionTracesSuccess('session-1', mockTraces1)
            sessionsLogic.actions.loadSessionTracesSuccess('session-2', mockTraces2)

            expect(sessionsLogic.values.sessionTraces).toEqual({
                'session-1': mockTraces1,
                'session-2': mockTraces2,
            })
        })

        it('clears session traces when filters change', async () => {
            const mockTraces = [{ id: 'trace-1' }] as any[]
            sessionsLogic.actions.loadSessionTracesSuccess('session-123', mockTraces)

            await expectLogic(sessionsLogic, () => {
                sharedLogic.actions.setDates('-30d', null)
            }).toMatchValues({
                sessionTraces: {},
            })
        })
    })

    describe('full traces data', () => {
        it('stores loaded full trace', async () => {
            const mockTrace = { id: 'trace-abc', events: [] } as any

            await expectLogic(sessionsLogic, () => {
                sessionsLogic.actions.loadFullTraceSuccess('trace-abc', mockTrace)
            }).toMatchValues({
                fullTraces: {
                    'trace-abc': mockTrace,
                },
            })
        })

        it('stores multiple full traces', async () => {
            const mockTrace1 = { id: 'trace-1' } as any
            const mockTrace2 = { id: 'trace-2' } as any

            sessionsLogic.actions.loadFullTraceSuccess('trace-1', mockTrace1)
            sessionsLogic.actions.loadFullTraceSuccess('trace-2', mockTrace2)

            expect(sessionsLogic.values.fullTraces).toEqual({
                'trace-1': mockTrace1,
                'trace-2': mockTrace2,
            })
        })

        it('clears full traces when filters change', async () => {
            const mockTrace = { id: 'trace-xyz' } as any
            sessionsLogic.actions.loadFullTraceSuccess('trace-xyz', mockTrace)

            await expectLogic(sessionsLogic, () => {
                sharedLogic.actions.setPropertyFilters([])
            }).toMatchValues({
                fullTraces: {},
            })
        })
    })
})
