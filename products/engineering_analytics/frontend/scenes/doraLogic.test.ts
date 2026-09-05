import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { DoraOverviewApi } from '../generated/api.schemas'
import { doraLogic } from './doraLogic'
import { engineeringAnalyticsLogic } from './engineeringAnalyticsLogic'

const DORA: DoraOverviewApi = {
    environment_scope: 'prod-us, prod-eu',
    environments: ['dev', 'prod-us', 'prod-eu'],
    selected_environments: ['prod-us', 'prod-eu'],
    github_teams: [],
    series_granularity: 'day',
    deploy_data_available: true,
    has_membership_data: false,
    deployment_count: 0,
    deployment_count_prev: 0,
    deployments_per_day: 0,
    deployments_per_day_prev: 0,
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
}

describe('doraLogic', () => {
    let logic: ReturnType<typeof doraLogic.build>
    let requests: URLSearchParams[]
    let releaseScopedRequest: () => void
    let scopedRequest: Promise<void>

    beforeEach(() => {
        requests = []
        scopedRequest = new Promise((resolve) => {
            releaseScopedRequest = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/engineering_analytics/dora/': async ({ request }) => {
                    const params = new URL(request.url).searchParams
                    requests.push(params)
                    const requested = [...new Set(params.getAll('environment').map((name) => name.trim()))]
                    const available = new Set(
                        params.get('repo') === 'example/repo' ? ['staging'] : [...DORA.environments, 'preview-pr-2']
                    )
                    if (requested.some((name) => !available.has(name))) {
                        return [400, { detail: 'Select a valid environment.', attr: 'environment' }]
                    }
                    if (params.get('repo') === 'example/repo') {
                        await scopedRequest
                        return [
                            200,
                            {
                                ...DORA,
                                environment_scope: 'staging',
                                environments: ['staging'],
                                selected_environments: ['staging'],
                            },
                        ]
                    }
                    return [
                        200,
                        {
                            ...DORA,
                            environment_scope: requested.length ? requested.join(', ') : DORA.environment_scope,
                            selected_environments: requested.length ? requested : DORA.selected_environments,
                        },
                    ]
                },
                '/api/projects/:team_id/engineering_analytics/sources/': [],
                '/api/projects/:team_id/engineering_analytics/ci_cards/': {
                    open_prs: 0,
                    repos: 0,
                    stuck: 0,
                    failing_ci: 0,
                },
                '/api/projects/:team_id/engineering_analytics/pull_requests/': {
                    items: [],
                    truncated: false,
                    limit: 1000,
                },
                '/api/projects/:team_id/engineering_analytics/workflow_health/': [],
                '/api/projects/:team_id/engineering_analytics/quarantine/': {
                    available: false,
                    entries: [],
                    parse_errors: [],
                    parse_warnings: [],
                    repo: null,
                    source_url: '',
                    generated_at: '2026-01-01T00:00:00Z',
                },
                '/api/projects/:team_id/engineering_analytics/trunk_quarantine/': {
                    available: false,
                    owners_resolved: true,
                    ttl_days: 15,
                    repository: 'example/repo',
                    trunk_url: null,
                    teams: [],
                    tests: [],
                },
            },
        })
        initKeaTests()
        ApiConfig.setCurrentProjectId(1)
        logic = doraLogic()
        logic.mount()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        logic.unmount()
    })

    it('shows both resolved production regions as selected on first load', async () => {
        await expectLogic(logic).toDispatchActions(['loadDoraSuccess'])
        expect(requests[0].getAll('environment')).toEqual([])
        expect(logic.values.selectedEnvironments).toEqual(['prod-us', 'prod-eu'])
        expect(logic.values.environmentOptions.map(({ key }) => key)).toEqual(['dev', 'prod-us', 'prod-eu'])
    })

    it('sends the visible selections as repeated parameters and restores production when cleared', async () => {
        await expectLogic(logic).toDispatchActions(['loadDoraSuccess'])
        await expectLogic(logic, () => logic.actions.setEnvironments(['prod-eu', 'dev'])).toDispatchActions([
            'loadDoraSuccess',
        ])
        expect(requests.at(-1)?.getAll('environment')).toEqual(['prod-eu', 'dev'])
        expect(logic.values.selectedEnvironments).toEqual(['prod-eu', 'dev'])

        await expectLogic(logic, () => logic.actions.setEnvironments([])).toDispatchActions(['loadDoraSuccess'])
        expect(requests.at(-1)?.getAll('environment')).toEqual([])
        expect(logic.values.selectedEnvironments).toEqual(['prod-us', 'prod-eu'])
    })

    it('uses the backend-validated environment selection and options', async () => {
        await expectLogic(logic).toDispatchActions(['loadDoraSuccess'])
        await expectLogic(logic, () =>
            logic.actions.setEnvironments([' prod-eu ', 'prod-eu', 'preview-pr-2'])
        ).toDispatchActions(['loadDoraSuccess'])

        expect(logic.values.selectedEnvironments).toEqual(['prod-eu', 'preview-pr-2'])
        expect(logic.values.environmentScopeLabel).toBe('prod-eu, preview-pr-2')
        expect(logic.values.environmentOptions.map(({ key }) => key)).toEqual([
            'dev',
            'prod-us',
            'prod-eu',
            'preview-pr-2',
        ])

        silenceKeaLoadersErrors()
        for (const environments of [['missing'], ['prod-eu', 'missing'], [' '], ['prod-eu', '']]) {
            await expectLogic(logic, () => logic.actions.setEnvironments(environments))
                .toDispatchActions(['loadDoraFailure'])
                .toMatchValues({
                    doraLoading: false,
                    doraFailed: true,
                    selectedEnvironments: ['prod-eu', 'preview-pr-2'],
                    environmentScopeLabel: 'prod-eu, preview-pr-2',
                })
            expect(logic.values.environmentOptions.map(({ key }) => key)).toEqual([
                'dev',
                'prod-us',
                'prod-eu',
                'preview-pr-2',
            ])
        }
    })

    it('resolves the new repository default instead of retaining an old environment or team', async () => {
        await expectLogic(logic).toDispatchActions(['loadDoraSuccess'])
        await expectLogic(logic, () => {
            logic.actions.setEnvironments(['dev'])
            logic.actions.setGithubTeam('team-example')
        }).toFinishAllListeners()
        engineeringAnalyticsLogic.actions.setScope('source-2', 'example/repo')
        expect(logic.values.selectedEnvironments).toEqual([])
        expect(logic.values.environmentOptions).toEqual([])
        expect(logic.values.environmentScopeLabel).toBe('production')

        await expectLogic(logic, () => releaseScopedRequest()).toFinishAllListeners()
        expect(requests.at(-1)?.get('source_id')).toEqual('source-2')
        expect(requests.at(-1)?.get('repo')).toEqual('example/repo')
        expect(requests.at(-1)?.getAll('environment')).toEqual([])
        expect(requests.at(-1)?.has('github_team')).toBe(false)
        expect(logic.values.dora).toMatchObject({ selected_environments: ['staging'] })
        expect(logic.values.selectedEnvironments).toEqual(['staging'])
        expect(logic.values.environmentOptions.map(({ key }) => key)).toEqual(['staging'])
    })
})
