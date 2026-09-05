import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { initKeaTests } from '~/test/init'

import { engineeringAnalyticsDora } from '../generated/api'
import type { DoraOverviewApi } from '../generated/api.schemas'
import { doraLogic } from './doraLogic'

jest.mock('../generated/api', () => ({
    engineeringAnalyticsCiCards: jest.fn().mockResolvedValue({ open_prs: 0, repos: 0, stuck: 0, failing_ci: 0 }),
    engineeringAnalyticsDora: jest.fn(),
    engineeringAnalyticsPullRequests: jest.fn().mockResolvedValue({ items: [], truncated: false, limit: 0 }),
    engineeringAnalyticsQuarantine: jest.fn().mockResolvedValue({ available: false, entries: [], source_url: '' }),
    engineeringAnalyticsSources: jest.fn().mockResolvedValue([]),
    engineeringAnalyticsTrunkQuarantine: jest.fn().mockResolvedValue({ available: false, teams: [], tests: [] }),
    engineeringAnalyticsWorkflowHealth: jest.fn().mockResolvedValue([]),
}))

const mockDora = engineeringAnalyticsDora as jest.MockedFunction<typeof engineeringAnalyticsDora>

function overview(environment_scope: string): DoraOverviewApi {
    return {
        deploy_data_available: true,
        environment_scope,
        environments: ['dev', 'prod-us', 'prod-eu'],
        has_membership_data: false,
        github_teams: [],
        deployment_count: 0,
        deployment_count_prev: 0,
        deployments_per_day: null,
        deployments_per_day_prev: null,
        median_merge_to_deploy_seconds: null,
        median_merge_to_deploy_seconds_prev: null,
        median_open_to_deploy_seconds: null,
        median_open_to_deploy_seconds_prev: null,
        deployed_pr_count: 0,
        deployed_pr_count_prev: 0,
        failed_deployment_count: 0,
        failed_deployment_count_prev: 0,
        failed_deployment_share: null,
        failed_deployment_share_prev: null,
        median_failed_deploy_to_next_success_seconds: null,
        median_failed_deploy_to_next_success_seconds_prev: null,
        merged_pr_count: 0,
        unattributed_merged_pr_share: null,
        latest_deploy_status_at: null,
        deployment_frequency_series: [],
        merge_to_deploy_series: [],
        open_to_merge_series: [],
        open_to_deploy_series: [],
        series_granularity: 'day',
    }
}

describe('doraLogic', () => {
    let logic: ReturnType<typeof doraLogic.build>

    beforeEach(() => {
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        mockDora.mockReset()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['the resolved default scope', 'prod-us, prod-eu', [], ['prod-us', 'prod-eu']],
        ['nothing for the persistent fallback', 'persistent', [], []],
        ["the user's picks over the default", 'prod-us, prod-eu', ['dev'], ['dev']],
    ])('the environment picker shows %s', async (_label, scope, picks, expected) => {
        mockDora.mockResolvedValue(overview(scope))
        logic = doraLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadDoraSuccess'])

        if (picks.length) {
            logic.actions.setEnvironments(picks)
        }

        expect(logic.values.selectedEnvironments).toEqual(expected)
    })
})
