import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    ExternalDataJobStatus,
    ExternalDataSource,
    ExternalDataSourceSchema,
    IntegrationType,
} from '~/types'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'

import * as signalsApi from '../generated/api'
import type { InboxOnboardingDraftApi, InboxOnboardingStateApi, SignalSourceConfigApi } from '../generated/api.schemas'
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

const declinedJiraDraft: InboxOnboardingDraftApi = {
    step: 'github',
    sources: [{ source_product: 'jira', source_type: 'issue', enabled: false }],
    scanner_ids: [],
    suggestions: [],
    automatic_implementation: false,
    implementation_priority: 'P1',
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
    let onboardingState: InboxOnboardingStateApi

    beforeEach(() => {
        warehouseSources = []
        onboardingState = { draft: null, completed_at: null }
        useMocks({
            get: {
                '/api/projects/:team_id/signals/onboarding/': () => [200, onboardingState],
                '/api/environments/:team_id/external_data_sources/': () => [
                    200,
                    { results: warehouseSources, count: warehouseSources.length, next: null, previous: null },
                ],
                '/api/projects/:team_id/error_tracking/issues/exists/': { exists: false },
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

    it.each([
        {
            source: 'jira' as const,
            warehouseType: 'Jira' as const,
            table: 'issues',
            recordType: SignalSourceType.Issue,
            refresh: false,
        },
        {
            source: 'sonarqube' as const,
            warehouseType: 'Sonarqube' as const,
            table: 'issues',
            recordType: SignalSourceType.ScannerFinding,
            refresh: true,
        },
        {
            source: 'github' as const,
            warehouseType: 'Github' as const,
            table: 'issues',
            recordType: SignalSourceType.Issue,
            refresh: false,
        },
        {
            source: 'linear' as const,
            warehouseType: 'Linear' as const,
            table: 'issues',
            recordType: SignalSourceType.Issue,
            refresh: false,
        },
        {
            source: 'intercom' as const,
            warehouseType: 'Intercom' as const,
            table: 'conversations',
            recordType: SignalSourceType.Ticket,
            refresh: false,
        },
    ])(
        'enables $source using its existing connection and required record type',
        async ({ source, warehouseType, table, recordType, refresh }) => {
            const configWrites: unknown[] = []
            const schemaWrites: unknown[] = []
            warehouseSources = [
                {
                    ...githubSource,
                    source_type: warehouseType,
                    schemas: [{ ...githubSchema('schema-1', table), sync_type: 'incremental' }],
                },
            ]
            useMocks({
                post: {
                    '/api/projects/:team_id/signals/source_configs/': async ({ request }) => {
                        configWrites.push(await request.json())
                        return [200, { ...githubIssuesConfig, source_product: source, source_type: recordType }]
                    },
                },
                patch: {
                    '/api/environments/:team_id/external_data_schemas/:id/': async ({ request }) => {
                        schemaWrites.push(await request.json())
                        return [200, {}]
                    },
                },
            })
            logic.actions.loadSourceConfigsSuccess([])
            sourcesDataLogic.actions.loadSourcesSuccess({ results: warehouseSources, next: null, previous: null })
            await expectLogic(logic, () =>
                logic.actions.initiateDataWarehouseSourceToggle(source)
            ).toFinishAllListeners()
            expect(logic.values.dataSourceSetupSource).toBeNull()
            expect(configWrites).toEqual(
                source === 'linear'
                    ? []
                    : [{ source_product: source, source_type: recordType, enabled: true, config: {} }]
            )
            if (source === 'linear') {
                expect(logic.values.linearTeamsPicker).toEqual({ enableOnSave: true, viaSetupWizard: false })
            }
            expect(schemaWrites).toEqual(refresh ? [{ should_sync: true, sync_type: 'full_refresh' }] : [])
            expect(logic.values.externalSourceStates[source].loading).toBe(false)
        }
    )

    it.each([
        ['image-only connection', 'search_analytics_by_query_page_image'],
        ['connection without schemas', null],
    ])('does not enable Search Console signals with an %s', async (_name, schemaName) => {
        const createConfig = jest.spyOn(signalsApi, 'signalsSourceConfigsCreate')
        const toastError = jest.spyOn(lemonToast, 'error')
        warehouseSources = [
            {
                ...githubSource,
                source_type: 'GoogleSearchConsole',
                schemas: schemaName ? [githubSchema('gsc-1', schemaName)] : [],
            },
        ]
        logic.actions.loadSourceConfigsSuccess([])
        sourcesDataLogic.actions.loadSourcesSuccess({ results: warehouseSources, next: null, previous: null })

        await expectLogic(logic, () =>
            logic.actions.initiateDataWarehouseSourceToggle('google_search_console')
        ).toFinishAllListeners()

        expect(createConfig).not.toHaveBeenCalled()
        expect(toastError).toHaveBeenCalledWith(expect.stringContaining('Add the Web search type'))
        expect(logic.values.externalSourceStates.google_search_console.loading).toBe(false)
        createConfig.mockRestore()
        toastError.mockRestore()
    })

    it.each(['/inbox', '/inbox/sources'])(
        'resumes Intercom setup after OAuth on %s and enables signals on completion',
        async (path) => {
            logic.unmount()
            router.actions.push(
                path,
                { setup: 'signal-sources', signal_source: 'intercom', integration_id: '7', source: 'saved-filter' },
                { tab: 'details' }
            )
            const callbackPath = router.values.location.pathname
            const intercomConfig = {
                ...githubIssuesConfig,
                source_product: SignalSourceProduct.Intercom,
                source_type: SignalSourceType.Ticket,
            }
            let saved = false
            const createConfig = jest.spyOn(signalsApi, 'signalsSourceConfigsCreate').mockImplementation(async () => {
                saved = true
                return intercomConfig
            })
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/source_configs/': () => [
                        200,
                        { results: saved ? [intercomConfig] : [] },
                    ],
                },
            })
            logic = signalSourcesLogic()
            logic.mount()
            logic.actions.loadSourceConfigsSuccess([])

            expect(logic.values.dataSourceSetupSource).toBe('intercom')
            const redirect = new URL(logic.values.dataSourceSetupOAuthRedirectUrl!, 'https://example.com')
            expect(redirect.pathname).toBe(callbackPath)
            expect(redirect.searchParams.get('signal_source')).toBe('intercom')
            expect(redirect.searchParams.get('source')).toBe('saved-filter')

            await expectLogic(logic, () => logic.actions.onDataSourceSetupComplete()).toFinishAllListeners()

            expect(createConfig).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
                source_product: 'intercom',
                source_type: 'ticket',
                enabled: true,
                config: {},
            })
            expect(logic.values.dataSourceSetupSource).toBeNull()
            expect(router.values.searchParams.signal_source).toBeUndefined()
            expect(router.values.searchParams.source).toBe('saved-filter')
            expect(
                logic.values.rosterGroups.find((group) => group.id === 'external')?.agents.map((agent) => agent.source)
            ).toContain('intercom')
            expect(
                logic.values.sourceCatalog.flatMap((group) => group.items.map((item) => item.agent.source))
            ).not.toContain('intercom')
            createConfig.mockRestore()
        }
    )

    it.each([
        { status: 200, reason: 'integration' },
        { status: 500, reason: 'default' },
    ])('waits for integrations before recommending sources, with a $status response', async ({ status, reason }) => {
        await expectLogic(logic).toFinishAllListeners()
        const response = deferred<void>()
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': async () => {
                    await response.promise
                    return status === 200
                        ? [200, { results: [{ id: 1, kind: 'github' }], next: null }]
                        : [500, { detail: 'Server error' }]
                },
            },
        })
        integrationsLogic.actions.clearIntegrations()
        integrationsLogic.actions.loadIntegrations()
        logic.actions.loadSourceConfigsSuccess([])
        sourcesDataLogic.actions.loadSourcesSuccess({ results: [], next: null, previous: null })

        expect(logic.values.visibleSourceRecommendations).toEqual([])

        response.resolve()
        await expectLogic(integrationsLogic).toFinishAllListeners()
        expect(logic.values.visibleSourceRecommendations.find(({ agent }) => agent.source === 'github')).toMatchObject({
            reason,
        })
    })

    // The roster shows what runs and the catalog shows the rest, with the recommendations built only
    // once both the configs and the connections are known. A recommendation computed from a half-loaded
    // picture would tell someone to connect a tool they already sync.
    it('rosters connected sources, filters the catalog, and recommends by effort once everything has loaded', () => {
        integrationsLogic.actions.loadIntegrationsSuccess([{ id: 1, kind: 'github' } as IntegrationType])
        logic.actions.loadSourceConfigsSuccess([
            {
                ...githubIssuesConfig,
                id: 'conversations_ticket',
                source_product: SignalSourceProduct.Conversations,
                source_type: SignalSourceType.Ticket,
                enabled: true,
            },
        ])
        expect(logic.values.recommendedSources).toEqual([])

        const recommended = (): string[][] =>
            logic.values.visibleSourceRecommendations.map(({ agent, reason }) => [agent.source, reason])
        sourcesDataLogic.actions.loadSourcesSuccess({ results: [], next: null, previous: null })
        expect(recommended()).toEqual([
            ['github', 'integration'],
            ['linear', 'default'],
        ])

        logic.actions.loadOnboardingStateSuccess({
            draft: declinedJiraDraft,
            completed_at: '2024-03-10T00:00:00Z',
        })
        sourcesDataLogic.actions.loadSourcesSuccess({
            results: [
                { ...githubSource, source_type: 'Jira', created_at: '2024-03-01T00:00:00Z' },
                { ...githubSource, id: 'source-gitea', source_type: 'Gitea', created_at: '2024-03-20T00:00:00Z' },
            ],
            next: null,
            previous: null,
        })
        const external = (): string[] =>
            logic.values.rosterGroups.find((group) => group.id === 'external')?.agents.map((agent) => agent.source) ??
            []
        expect(external()).toEqual(['jira', 'gitea'])
        expect(logic.values.externalSourceStates.jira).toMatchObject({ connected: true, requiresSetup: false })
        expect(logic.values.externalSourceStates.sentry).toMatchObject({ connected: false, requiresSetup: true })
        expect(recommended()).toEqual([['github', 'integration']])
        const catalogSources = (): string[] =>
            logic.values.sourceCatalog.flatMap((group) => group.items.map((item) => item.agent.source))
        expect(catalogSources()).not.toContain('jira')
        expect(catalogSources()).not.toContain('gitea')
        expect(logic.values.sourceCatalog[0].category).toBe('Recommended for you')
        expect(catalogSources().filter((source) => source === 'github')).toHaveLength(1)

        const connectedSources = (['Gitea', 'Bugsnag', 'Honeybadger', 'Raygun'] as const).map((source_type) => ({
            ...githubSource,
            id: source_type,
            source_type,
        }))
        sourcesDataLogic.actions.loadSourcesSuccess({ results: connectedSources, next: null, previous: null })
        expect(recommended()).toEqual([['github', 'integration']])
        logic.actions.hideSourceRecommendations()
        expect(recommended()).toEqual([])
        sourcesDataLogic.actions.loadSourcesSuccess({
            results: [...connectedSources, { ...githubSource, id: 'rollbar', source_type: 'Rollbar' }],
            next: null,
            previous: null,
        })
        expect(recommended()).toEqual([])
        expect(external()).toContain('rollbar')

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ENGINEERING_ANALYTICS]: true })
        expect(logic.values.sourceCategoryOptions).toContainEqual({ label: 'Engineering', value: 'Engineering' })
        logic.actions.setSourceCategory('Engineering')
        expect(logic.values.sourceCatalog.map((group) => group.items.map((item) => item.agent.source))).toEqual([
            ['engineering_analytics'],
        ])
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.ENGINEERING_ANALYTICS]: false })
        expect(logic.values.sourceCategoryOptions).not.toContainEqual({ label: 'Engineering', value: 'Engineering' })
        expect(logic.values.sourceCatalog).toEqual([])

        logic.actions.setSourceCategory('Error tracking')
        logic.actions.setSourceSearchQuery('SENTRY')
        expect(
            logic.values.sourceCatalog.map((group) => [group.category, group.items.map((item) => item.agent.source)])
        ).toEqual([['Error tracking', ['sentry']]])
        logic.actions.openDataSourceSetup('sentry')
        logic.actions.closeDataSourceSetup()
        expect(logic.values.sourceSearchQuery).toBe('SENTRY')
        expect(logic.values.sourceCategory).toBe('Error tracking')
        logic.actions.setSourceSearchQuery('')
        logic.actions.setSourceCategory('')
        expect(logic.values.sourceCatalog.length).toBeGreaterThan(1)
        expect(logic.values.rosterGroups.find((group) => group.id === 'posthog')?.agents.length).toBeGreaterThan(0)
    })

    it.each([
        { name: 'completion without a draft', draft: null, expected: ['jira'] },
        {
            name: 'completion without a source choice',
            draft: { ...declinedJiraDraft, sources: [] },
            expected: ['jira'],
        },
        { name: 'an explicit source rejection', draft: declinedJiraDraft, expected: [] },
    ])('refreshes recommendations after $name', async (state) => {
        warehouseSources = [{ ...githubSource, source_type: 'Jira', created_at: '2024-03-01T00:00:00Z' }]
        onboardingState = { draft: state.draft, completed_at: null }
        sourcesDataLogic.actions.loadSourcesSuccess({ results: warehouseSources, next: null, previous: null })
        await expectLogic(logic, () => logic.actions.loadSourceConfigs()).toFinishAllListeners()
        expect(logic.values.recommendedSources.map(({ agent }) => agent.source)).toEqual(['jira'])

        onboardingState = { ...onboardingState, completed_at: '2024-03-10T00:00:00Z' }
        await expectLogic(logic, () => logic.actions.loadSourceConfigs()).toFinishAllListeners()
        expect(logic.values.recommendedSources.map(({ agent }) => agent.source)).toEqual(state.expected)
    })

    it.each(['project', 'user'])('isolates recommendation dismissals by %s across reloads', (scope) => {
        const originalContext = window.POSTHOG_APP_CONTEXT!
        logic.actions.hideSourceRecommendations()
        expect(logic.values.sourceRecommendationsDismissal).toEqual([])
        logic.unmount()

        const otherTeam =
            scope === 'project' ? { ...MOCK_DEFAULT_TEAM, id: MOCK_DEFAULT_TEAM.id + 1 } : MOCK_DEFAULT_TEAM
        window.POSTHOG_APP_CONTEXT = {
            ...originalContext,
            current_user: { ...originalContext.current_user!, uuid: 'another-user' },
        }
        if (scope === 'project') {
            window.POSTHOG_APP_CONTEXT.current_user = originalContext.current_user
        }
        initKeaTests(true, otherTeam)
        logic = signalSourcesLogic()
        logic.mount()
        expect(logic.values.sourceRecommendationsDismissal).toBeNull()
        logic.unmount()

        window.POSTHOG_APP_CONTEXT = originalContext
        initKeaTests()
        logic = signalSourcesLogic()
        logic.mount()
        expect(logic.values.sourceRecommendationsDismissal).toEqual([])
    })

    it('carries the card guidance onto an error tracking signal type turned on later', async () => {
        // Error tracking is one guidance box over three rows. A row created after the guidance was
        // written would otherwise start empty, so that one trigger would report everything while the
        // card still reads as steered.
        const steeredRow = (sourceType: SignalSourceType): any => ({
            ...githubIssuesConfig,
            id: `config-${sourceType}`,
            source_product: SignalSourceProduct.ErrorTracking,
            source_type: sourceType,
            config: { steering: 'Ignore errors from localhost.' },
        })
        const create = jest.spyOn(api.signalSourceConfigs, 'create').mockResolvedValue(githubIssuesConfig as any)
        logic.actions.loadSourceConfigsSuccess([
            steeredRow(SignalSourceType.IssueCreated),
            steeredRow(SignalSourceType.IssueReopened),
        ])

        await expectLogic(logic, () => {
            logic.actions.toggleErrorTrackingType(SignalSourceType.IssueSpiking)
        }).toDispatchActions(['loadSourceConfigs'])

        expect(create).toHaveBeenCalledWith(
            expect.objectContaining({
                source_type: SignalSourceType.IssueSpiking,
                config: { steering: 'Ignore errors from localhost.' },
            })
        )
        create.mockRestore()
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
        const createSourceConfig = jest
            .spyOn(signalsApi, 'signalsSourceConfigsCreate')
            .mockResolvedValue(githubIssuesConfig as SignalSourceConfigApi)
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

    // Before the list loads, an existing row looks new. Creating it again fails on the unique
    // constraint, so the toggle has to refuse and let go of its spinner instead.
    it.each([
        {
            name: 'Support',
            toggle: (mountedLogic: typeof logic) => mountedLogic.actions.toggleConversations(),
            isToggling: (mountedLogic: typeof logic) => mountedLogic.values.isConversationsToggling,
        },
        {
            name: 'Error tracking',
            toggle: (mountedLogic: typeof logic) => mountedLogic.actions.toggleErrorTracking(),
            isToggling: (mountedLogic: typeof logic) => mountedLogic.values.isErrorTrackingToggling,
        },
        {
            name: 'an Error tracking signal type',
            toggle: (mountedLogic: typeof logic) =>
                mountedLogic.actions.toggleErrorTrackingType(SignalSourceType.IssueSpiking),
            isToggling: () => false,
        },
    ])('creates no row for $name while the source list has not loaded', async ({ toggle, isToggling }) => {
        const createSourceConfig = jest
            .spyOn(signalsApi, 'signalsSourceConfigsCreate')
            .mockResolvedValue(githubIssuesConfig as SignalSourceConfigApi)
        const legacyCreate = jest.spyOn(api.signalSourceConfigs, 'create')
        expect(logic.values.sourceConfigs).toBeNull()

        toggle(logic)
        await expectLogic(logic).toFinishAllListeners()

        expect(createSourceConfig).not.toHaveBeenCalled()
        expect(legacyCreate).not.toHaveBeenCalled()
        legacyCreate.mockRestore()
        expect(isToggling(logic)).toBe(false)
        createSourceConfig.mockRestore()
    })

    it('reports a failed toggle when another source is toggled while it saves', async () => {
        let rejectUpdate!: (error: unknown) => void
        const updatePromise = new Promise<never>((_, reject) => {
            rejectUpdate = reject
        })
        const updateSourceConfig = jest
            .spyOn(signalsApi, 'signalsSourceConfigsPartialUpdate')
            .mockReturnValue(updatePromise)
        const createSourceConfig = jest
            .spyOn(signalsApi, 'signalsSourceConfigsCreate')
            .mockResolvedValue(githubIssuesConfig as SignalSourceConfigApi)
        const toastError = jest.spyOn(lemonToast, 'error')
        logic.actions.loadSourceConfigsSuccess([
            {
                ...githubIssuesConfig,
                id: 'config-conversations',
                source_product: SignalSourceProduct.Conversations,
                source_type: SignalSourceType.Ticket,
                enabled: false,
            },
        ])

        logic.actions.toggleConversations()
        logic.actions.toggleEvalReports()
        rejectUpdate({ detail: 'Support is not set up for this project.' })
        await expectLogic(logic).toFinishAllListeners()

        expect(toastError).toHaveBeenCalledWith('Support is not set up for this project.')
        expect(logic.values.isConversationsToggling).toBe(false)
        updateSourceConfig.mockRestore()
        createSourceConfig.mockRestore()
        toastError.mockRestore()
    })

    it('uses only eval reports for the AI observability signal source', async () => {
        const createSourceConfig = jest.spyOn(signalsApi, 'signalsSourceConfigsCreate').mockResolvedValue({
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

        expect(createSourceConfig).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
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
                mountedLogic.actions.loadProductDataEventsSuccess(new Set(['$exception']))
                mountedLogic.actions.loadProductDataEventsFailure('Failed')
            },
            enabled: null,
            dataStatus: 'error',
        },
        {
            name: 'when a successful check finds no recent exceptions',
            arrange: (mountedLogic: typeof logic) => mountedLogic.actions.loadProductDataEventsSuccess(new Set()),
            enabled: false,
            dataStatus: 'none',
        },
        {
            name: 'when the issue check fails and no recent exceptions exist',
            arrange: (mountedLogic: typeof logic) => {
                mountedLogic.actions.setErrorTrackingHasIssues(null)
                mountedLogic.actions.loadProductDataEventsSuccess(new Set())
            },
            enabled: null,
            dataStatus: 'error',
        },
        {
            name: 'when a successful check finds recent exceptions',
            arrange: (mountedLogic: typeof logic) =>
                mountedLogic.actions.loadProductDataEventsSuccess(new Set(['$exception'])),
            enabled: true,
            dataStatus: 'recent',
        },
    ])('reports Error tracking as $dataStatus $name', ({ arrange, enabled, dataStatus }) => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            autocapture_exceptions_opt_in: false,
        })

        logic.actions.setErrorTrackingHasIssues(false)
        arrange(logic)

        expect(logic.values.productStatusBySource.error_tracking).toMatchObject({ enabled, dataStatus })
    })

    it('keeps loaded product statuses visible until a background refresh completes', async () => {
        const refresh = deferred<void>()
        useMocks({
            get: {
                '/api/projects/:team_id/event_definitions/': async () => {
                    await refresh.promise
                    return [200, { results: [], count: 0, next: null }]
                },
            },
        })
        logic.actions.setErrorTrackingHasIssues(false)
        logic.actions.loadProductDataEventsSuccess(new Set(['$exception', '$ai_generation', '$pageview']))
        const statuses = logic.values.productStatusBySource

        logic.actions.loadProductDataEvents()
        expect(logic.values.productDataEventsLoading).toBe(true)
        expect(logic.values.productStatusBySource).toEqual(statuses)

        refresh.resolve()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.productStatusBySource.llm_analytics?.dataStatus).toBe('none')
    })

    it('recognizes existing Error tracking issues without recent event definitions or browser autocapture', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/error_tracking/issues/exists/': { exists: true },
                '/api/projects/:team_id/event_definitions/': { results: [], count: 0, next: null },
            },
        })
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, autocapture_exceptions_opt_in: false })

        await expectLogic(logic, () => logic.actions.loadProductDataEvents()).toFinishAllListeners()

        expect(logic.values.productStatusBySource.error_tracking).toMatchObject({
            enabled: true,
            dataStatus: 'unavailable',
        })
    })

    it('uses only recently seen event definitions as product data', async () => {
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
            logic.actions.loadProductDataEvents()
        }).toFinishAllListeners()

        expect(logic.values.productDataEvents).toEqual(new Set(['$exception']))
        expect(logic.values.productStatusBySource.error_tracking).toMatchObject({
            enabled: true,
            dataStatus: 'recent',
        })
        expect(logic.values.productStatusBySource.analytics?.dataStatus).toBe('none')
        expect(logic.values.productStatusBySource.llm_analytics?.dataStatus).toBe('none')
    })

    it('keeps product enablement loading until the refreshed team is available', async () => {
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

        logic.actions.enableSourceProduct('error_tracking')
        expect(logic.values.enablingProduct).toBe('error_tracking')

        enablementResponse.resolve([200, { results: { error_tracking: 'enabled' } }])
        await teamRequestStarted.promise
        expect(logic.values.enablingProduct).toBe('error_tracking')

        teamResponse.resolve([
            200,
            {
                ...MOCK_DEFAULT_TEAM,
                autocapture_exceptions_opt_in: true,
            },
        ])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.enablingProduct).toBeNull()
        expect(logic.values.productStatusBySource.error_tracking?.enabled).toBe(true)
    })
})
