import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    engineeringAnalyticsAuthorFriction,
    engineeringAnalyticsCiCards,
    engineeringAnalyticsPullRequests,
    engineeringAnalyticsQuarantine,
    engineeringAnalyticsSources,
    engineeringAnalyticsTrunkQuarantine,
    engineeringAnalyticsWorkflowHealth,
} from '../generated/api'
import type { AuthorFrictionApi } from '../generated/api.schemas'
import { authorFrictionLogic } from './authorFrictionLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsAuthorFriction: jest.fn(),
    engineeringAnalyticsCiCards: jest.fn(),
    engineeringAnalyticsPullRequests: jest.fn(),
    engineeringAnalyticsQuarantine: jest.fn(),
    engineeringAnalyticsSources: jest.fn(),
    engineeringAnalyticsTrunkQuarantine: jest.fn(),
    engineeringAnalyticsWorkflowHealth: jest.fn(),
}))

const mockFriction = engineeringAnalyticsAuthorFriction as jest.MockedFunction<
    typeof engineeringAnalyticsAuthorFriction
>

function author(name: string, rank: number, teams: string[]): AuthorFrictionApi {
    return {
        author: name,
        avatar_url: '',
        score: 3 - rank * 0.5,
        groups: [],
        pr_count: 5,
        rank,
        rank_low: rank,
        rank_high: rank,
        teams,
    }
}

describe('authorFrictionLogic', () => {
    let logic: ReturnType<typeof authorFrictionLogic.build>

    beforeEach(() => {
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        jest.clearAllMocks()
        mockFriction.mockResolvedValue({
            available: true,
            window_days: 30,
            ranked_author_count: 3,
            github_team: null,
            has_membership_data: true,
            items: [author('blocked', 1, []), author('typical', 2, ['pair']), author('calm', 3, ['pair'])],
            teams: [],
        })
        ;(engineeringAnalyticsCiCards as jest.Mock).mockResolvedValue({
            open_prs: 0,
            repos: 1,
            stuck: 0,
            failing_ci: 0,
        })
        ;(engineeringAnalyticsPullRequests as jest.Mock).mockResolvedValue({ items: [], truncated: false, limit: 1000 })
        ;(engineeringAnalyticsQuarantine as jest.Mock).mockResolvedValue({
            available: false,
            entries: [],
            parse_errors: [],
            parse_warnings: [],
            repo: null,
            source_url: '',
            generated_at: '',
        })
        ;(engineeringAnalyticsSources as jest.Mock).mockResolvedValue([])
        ;(engineeringAnalyticsTrunkQuarantine as jest.Mock).mockResolvedValue({
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
        ;(engineeringAnalyticsWorkflowHealth as jest.Mock).mockResolvedValue([])
    })

    afterEach(() => logic?.unmount())

    it('keeps repository ranks under a team filter and reloads for a new scope or a refresh', async () => {
        logic = authorFrictionLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFrictionSuccess'])

        logic.actions.setGithubTeam('pair')
        expect(logic.values.teamOptions).toEqual(['pair'])
        expect(logic.values.authors.map(({ author, rank }) => [author, rank])).toEqual([
            ['typical', 2],
            ['calm', 3],
        ])

        logic.actions.setScope('source-2', 'PostHog/posthog-js')
        await expectLogic(logic).toDispatchActions(['loadFrictionSuccess'])
        expect(mockFriction).toHaveBeenLastCalledWith('1', { source_id: 'source-2', repo: 'PostHog/posthog-js' })
        expect(logic.values.githubTeam).toBeNull()

        logic.actions.refresh()
        await expectLogic(logic).toDispatchActions(['loadFrictionSuccess'])
        expect(mockFriction).toHaveBeenCalledTimes(3)
    })
})
