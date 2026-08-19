import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, ExternalDataJobStatus, ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import { signalSourcesLogic } from './signalSourcesLogic'
import { SignalSourceProduct, SignalSourceType } from './types'

const githubSchema = (id: string, name: string): ExternalDataSourceSchema => ({
    id,
    name,
    label: null,
    should_sync: true,
    incremental: false,
    sync_type: 'full_refresh',
    sync_time_of_day: null,
    latest_error: null,
    incremental_field: null,
    incremental_field_type: null,
    sync_frequency: '24hour',
    primary_key_columns: null,
})

const githubSource: ExternalDataSource = {
    id: 'src-1',
    source_id: 'source-1',
    connection_id: 'connection-1',
    status: ExternalDataJobStatus.Completed,
    source_type: 'Github',
    prefix: null,
    description: null,
    created_via: 'web',
    latest_error: null,
    schemas: [
        githubSchema('sc-0', 'issues'),
        githubSchema('sc-1', 'workflow_runs'),
        githubSchema('sc-2', 'pull_requests'),
        githubSchema('sc-3', 'workflow_jobs'),
    ],
    sync_frequency: '24hour',
    job_inputs: {},
    revenue_analytics_config: { enabled: false, include_invoiceless_charges: false },
    user_access_level: AccessControlLevel.Manager,
}

const githubIssuesConfig = {
    id: 'config-1',
    source_product: SignalSourceProduct.Github,
    source_type: SignalSourceType.Issue,
    enabled: true,
    config: {},
    created_at: '2026-07-27T00:00:00Z',
    updated_at: '2026-07-27T00:00:00Z',
    status: null,
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolvePromise!: (value: T) => void
    const promise = new Promise<T>((resolve) => {
        resolvePromise = resolve
    })
    return { promise, resolve: resolvePromise }
}

describe('signalSourcesLogic', () => {
    let logic: ReturnType<typeof signalSourcesLogic.build>
    let warehouseSources: ExternalDataSource[]

    beforeEach(() => {
        warehouseSources = []
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/': () => [
                    200,
                    { results: warehouseSources, count: warehouseSources.length, next: null, previous: null },
                ],
                '/api/projects/:team_id/signals/source_configs/': () => [
                    200,
                    { results: [], count: 0, next: null, previous: null },
                ],
            },
            put: {
                '/api/projects/:team_id/engineering_analytics/ci-signals-config/': () => [
                    200,
                    { configured: true, enabled: true, sync_status: 'completed' },
                ],
            },
        })
        initKeaTests()
        logic = signalSourcesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The cached sources list is null right after mount (loadSources is debounced). Reading it
    // directly misread that as "no source connected" and opened the connect form, duplicating an
    // already-connected source. Enabling must reuse the existing source; only a genuinely empty
    // account should reach the connect form.
    it.each([
        {
            name: 'enables in place when a GitHub source exists but the list has not loaded',
            sources: [githubSource],
            action: 'loadCiSignalsConfigSuccess',
            setup: null,
        },
        {
            name: 'opens the connect form only when no GitHub source is connected',
            sources: [],
            action: 'openDataSourceSetup',
            setup: 'engineering_analytics',
        },
    ])('$name', async ({ sources, action, setup }) => {
        warehouseSources = sources
        expect(logic.values.dataWarehouseSources).toBeNull()

        await expectLogic(logic, () => {
            logic.actions.toggleCiSignals()
        }).toDispatchActions(['toggleCiSignals', action])

        expect(logic.values.dataSourceSetupSource).toBe(setup)
    })

    it('keeps an enabled source enabled when its config loads during the source lookup', async () => {
        let resolveSources!: (sources: Awaited<ReturnType<typeof api.externalDataSources.list>>) => void
        const sourcesPromise = new Promise<Awaited<ReturnType<typeof api.externalDataSources.list>>>((resolve) => {
            resolveSources = resolve
        })
        const listSources = jest.spyOn(api.externalDataSources, 'list').mockReturnValue(sourcesPromise)
        const updateSourceConfig = jest.spyOn(api.signalSourceConfigs, 'update').mockResolvedValue(githubIssuesConfig)

        logic.actions.initiateDataWarehouseSourceToggle('github')
        expect(logic.values.isGithubIssuesToggling).toBe(true)
        logic.actions.loadSourceConfigsSuccess([githubIssuesConfig])
        resolveSources({
            results: [githubSource],
            next: null,
            previous: null,
        })

        await expectLogic(logic).toFinishAllListeners()

        expect(listSources).toHaveBeenCalledTimes(1)
        expect(updateSourceConfig).not.toHaveBeenCalled()
        expect(logic.values.githubIssuesConfig?.enabled).toBe(true)
        expect(logic.values.isGithubIssuesToggling).toBe(false)
    })

    it('ignores repeated clicks while the source lookup is pending', async () => {
        let resolveSources!: (sources: Awaited<ReturnType<typeof api.externalDataSources.list>>) => void
        const sourcesPromise = new Promise<Awaited<ReturnType<typeof api.externalDataSources.list>>>((resolve) => {
            resolveSources = resolve
        })
        const listSources = jest.spyOn(api.externalDataSources, 'list').mockReturnValue(sourcesPromise)
        const createSourceConfig = jest.spyOn(api.signalSourceConfigs, 'create').mockResolvedValue(githubIssuesConfig)
        logic.actions.loadSourceConfigsSuccess([])

        logic.actions.initiateDataWarehouseSourceToggle('github')
        logic.actions.initiateDataWarehouseSourceToggle('github')

        expect(logic.values.isGithubIssuesToggling).toBe(true)
        expect(listSources).toHaveBeenCalledTimes(1)
        resolveSources({
            results: [githubSource],
            next: null,
            previous: null,
        })

        await expectLogic(logic).toFinishAllListeners()

        expect(createSourceConfig).toHaveBeenCalledTimes(1)
        expect(logic.values.isGithubIssuesToggling).toBe(false)
    })

    it('uses only eval reports for the AI observability signal source', async () => {
        const createSourceConfig = jest.spyOn(api.signalSourceConfigs, 'create').mockResolvedValue({
            id: 'config-evaluation-reports',
            source_product: SignalSourceProduct.LlmAnalytics,
            source_type: SignalSourceType.EvaluationReport,
            enabled: true,
            config: {},
            created_at: '2026-07-30T00:00:00Z',
            updated_at: '2026-07-30T00:00:00Z',
            status: null,
        })
        logic.actions.loadSourceConfigsSuccess([
            {
                id: 'retired-evaluation-config',
                source_product: SignalSourceProduct.LlmAnalytics,
                source_type: SignalSourceType.Evaluation,
                enabled: true,
                config: { evaluation_ids: ['evaluation-1'] },
                created_at: '2026-07-30T00:00:00Z',
                updated_at: '2026-07-30T00:00:00Z',
                status: null,
            },
        ])

        expect(logic.values.enabledSourcesCount).toBe(0)

        logic.actions.toggleEvalReports()
        await expectLogic(logic).toFinishAllListeners()

        expect(createSourceConfig).toHaveBeenCalledWith({
            source_product: SignalSourceProduct.LlmAnalytics,
            source_type: SignalSourceType.EvaluationReport,
            enabled: true,
            config: {},
        })
    })

    it.each([
        {
            name: 'while recent data is loading',
            arrange: (_mountedLogic: typeof logic) => undefined,
            enabled: null,
            dataStatus: 'loading',
        },
        {
            name: 'when the recent data check fails',
            arrange: (mountedLogic: typeof logic) => {
                mountedLogic.actions.loadToolDataEventsSuccess(new Set(['$exception']))
                mountedLogic.actions.loadToolDataEventsFailure('Failed')
            },
            enabled: null,
            dataStatus: 'error',
        },
        {
            name: 'when a successful check finds no recent exceptions',
            arrange: (mountedLogic: typeof logic) => mountedLogic.actions.loadToolDataEventsSuccess(new Set()),
            enabled: false,
            dataStatus: 'none',
        },
        {
            name: 'when a successful check finds recent exceptions',
            arrange: (mountedLogic: typeof logic) =>
                mountedLogic.actions.loadToolDataEventsSuccess(new Set(['$exception'])),
            enabled: true,
            dataStatus: 'recent',
        },
    ])('reports Error tracking as $dataStatus $name', ({ arrange, enabled, dataStatus }) => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            autocapture_exceptions_opt_in: false,
        })

        arrange(logic)

        expect(logic.values.toolStatusBySource.error_tracking).toMatchObject({ enabled, dataStatus })
    })

    it('uses only recently seen event definitions as tool data', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/event_definitions/': ({ request }) => {
                    const excludeStale = new URL(request.url).searchParams.get('exclude_stale') === 'true'
                    const results = excludeStale
                        ? [
                              { name: '$exception', last_seen_at: '2026-08-09T00:00:00Z' },
                              { name: '$pageview', last_seen_at: null },
                          ]
                        : [
                              { name: '$exception', last_seen_at: '2026-08-09T00:00:00Z' },
                              { name: '$pageview', last_seen_at: null },
                              { name: '$ai_trace', last_seen_at: '2026-01-01T00:00:00Z' },
                          ]
                    return [200, { count: results.length, next: null, previous: null, results }]
                },
            },
        })
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            autocapture_exceptions_opt_in: false,
        })

        await expectLogic(logic, () => {
            logic.actions.loadToolDataEvents()
        }).toFinishAllListeners()

        expect(logic.values.toolDataEvents).toEqual(new Set(['$exception']))
        expect(logic.values.toolStatusBySource.error_tracking).toMatchObject({
            enabled: true,
            dataStatus: 'recent',
        })
        expect(logic.values.toolStatusBySource.analytics?.dataStatus).toBe('none')
        expect(logic.values.toolStatusBySource.llm_analytics?.dataStatus).toBe('none')
    })

    it('keeps tool enablement loading until the refreshed team is available', async () => {
        const enablementResponse = deferred<[number, { results: Record<string, string> }]>()
        const teamResponse = deferred<[number, typeof MOCK_DEFAULT_TEAM]>()
        const teamRequestStarted = deferred<void>()
        useMocks({
            post: {
                '/api/projects/:team_id/product_enablement/': () => enablementResponse.promise,
            },
            get: {
                '/api/environments/:team_id/': () => {
                    teamRequestStarted.resolve()
                    return teamResponse.promise
                },
            },
        })
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            autocapture_exceptions_opt_in: false,
        })

        logic.actions.enableSourceTool('error_tracking')
        expect(logic.values.enablingTool).toBe('error_tracking')

        enablementResponse.resolve([200, { results: { error_tracking: 'enabled' } }])
        await teamRequestStarted.promise
        expect(logic.values.enablingTool).toBe('error_tracking')

        teamResponse.resolve([
            200,
            {
                ...MOCK_DEFAULT_TEAM,
                autocapture_exceptions_opt_in: true,
            },
        ])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.enablingTool).toBeNull()
        expect(logic.values.toolStatusBySource.error_tracking?.enabled).toBe(true)
    })
})
