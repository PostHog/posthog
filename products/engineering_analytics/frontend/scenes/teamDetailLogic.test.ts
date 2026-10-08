import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    engineeringAnalyticsCiCards,
    engineeringAnalyticsPullRequests,
    engineeringAnalyticsQuarantine,
    engineeringAnalyticsSources,
    engineeringAnalyticsTeamCiActivity,
    engineeringAnalyticsTeamCiHealth,
    engineeringAnalyticsTeamMergeTrend,
    engineeringAnalyticsTrunkQuarantine,
    engineeringAnalyticsWorkflowHealth,
} from '../generated/api'
import { engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import { teamDetailLogic } from './teamDetailLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsCiCards: jest.fn(),
    engineeringAnalyticsPullRequests: jest.fn(),
    engineeringAnalyticsQuarantine: jest.fn(),
    engineeringAnalyticsSources: jest.fn(),
    engineeringAnalyticsTeamCiActivity: jest.fn(),
    engineeringAnalyticsTeamCiHealth: jest.fn(),
    engineeringAnalyticsTeamMergeTrend: jest.fn(),
    engineeringAnalyticsTrunkQuarantine: jest.fn(),
    engineeringAnalyticsWorkflowHealth: jest.fn(),
}))

const mockCards = engineeringAnalyticsCiCards as jest.MockedFunction<typeof engineeringAnalyticsCiCards>
const mockPullRequests = engineeringAnalyticsPullRequests as jest.MockedFunction<
    typeof engineeringAnalyticsPullRequests
>
const mockQuarantine = engineeringAnalyticsQuarantine as jest.MockedFunction<typeof engineeringAnalyticsQuarantine>
const mockSources = engineeringAnalyticsSources as jest.MockedFunction<typeof engineeringAnalyticsSources>
const mockActivity = engineeringAnalyticsTeamCiActivity as jest.MockedFunction<
    typeof engineeringAnalyticsTeamCiActivity
>
const mockHealth = engineeringAnalyticsTeamCiHealth as jest.MockedFunction<typeof engineeringAnalyticsTeamCiHealth>
const mockMergeTrend = engineeringAnalyticsTeamMergeTrend as jest.MockedFunction<
    typeof engineeringAnalyticsTeamMergeTrend
>
const mockTrunkQuarantine = engineeringAnalyticsTrunkQuarantine as jest.MockedFunction<
    typeof engineeringAnalyticsTrunkQuarantine
>
const mockWorkflowHealth = engineeringAnalyticsWorkflowHealth as jest.MockedFunction<
    typeof engineeringAnalyticsWorkflowHealth
>

describe('teamDetailLogic', () => {
    let logic: ReturnType<typeof teamDetailLogic.build>
    let unmountFilters: (() => void) | undefined

    beforeEach(() => {
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        jest.clearAllMocks()
        mockCards.mockResolvedValue({ open_prs: 0, repos: 1, stuck: 0, failing_ci: 0 })
        mockPullRequests.mockResolvedValue({ items: [], truncated: false, limit: 1000 })
        mockQuarantine.mockResolvedValue({
            available: false,
            entries: [],
            parse_errors: [],
            parse_warnings: [],
            repo: null,
            source_url: '',
            generated_at: '',
        })
        mockSources.mockResolvedValue([])
        mockActivity.mockResolvedValue({ owner_team: 'team-replay', tests: [], truncated_tests: false })
        mockHealth.mockResolvedValue({ items: [], truncated: false, limit: 100 })
        mockMergeTrend.mockResolvedValue({ owner_team: 'team-replay', has_membership_data: true, points: [] })
        mockTrunkQuarantine.mockResolvedValue({
            available: false,
            owners_resolved: false,
            ttl_days: 15,
            repository: '',
            trunk_url: null,
            truncated: false,
            limit: 500,
            teams: [],
            tests: [],
        })
        mockWorkflowHealth.mockResolvedValue([])
    })

    afterEach(() => {
        logic?.unmount()
        unmountFilters?.()
        unmountFilters = undefined
    })

    it('reloads team CI health and merge trend for the shared date range', async () => {
        const filters = engineeringAnalyticsFiltersLogic()
        unmountFilters = filters.mount()
        logic = teamDetailLogic({ ownerTeam: 'team-replay', sourceId: 'source-1' })
        logic.mount()

        await expectLogic(logic).toDispatchActionsInAnyOrder([
            'loadActivitySuccess',
            'loadHealthRowSuccess',
            'loadMergeTrendSuccess',
        ])
        expect(mockActivity).toHaveBeenCalledTimes(1)

        filters.actions.setDateRange('2026-06-01', '2026-06-30')
        await expectLogic(logic).toDispatchActionsInAnyOrder(['loadHealthRowSuccess', 'loadMergeTrendSuccess'])

        expect(mockHealth).toHaveBeenLastCalledWith('1', {
            date_from: '2026-06-01',
            date_to: '2026-06-30',
            owner_team: 'team-replay',
            limit: 1,
            source_id: 'source-1',
        })
        expect(mockMergeTrend).toHaveBeenLastCalledWith('1', {
            owner_team: 'team-replay',
            date_from: '2026-06-01',
            date_to: '2026-06-30',
            source_id: 'source-1',
        })
        expect(mockActivity).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['a preset over 30 days', '-90d', null],
        ['a fixed range over 30 days', '2026-05-01', '2026-06-30'],
    ])('resets %s to the team default instead of requesting it', async (_label, dateFrom, dateTo) => {
        const filters = engineeringAnalyticsFiltersLogic()
        unmountFilters = filters.mount()
        filters.actions.setDateRange(dateFrom, dateTo)
        logic = teamDetailLogic({ ownerTeam: 'team-replay', sourceId: 'source-1' })
        logic.mount()

        await expectLogic(logic).toDispatchActionsInAnyOrder(['loadHealthRowSuccess', 'loadMergeTrendSuccess'])

        expect(filters.values.dateFrom).toEqual('-14d')
        expect(filters.values.dateTo).toBeNull()
        for (const mock of [mockHealth, mockMergeTrend]) {
            expect(mock.mock.calls.map(([, params]) => params?.date_from)).toEqual(['-14d'])
        }
    })
})
