import { MakeLogicType, actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { projectLogic } from 'scenes/projectLogic'

import { wizardRunsList } from './generated/api'
import type { RunEnvironmentEnumApi, WizardRunApi, WizardRunStatusEnumApi } from './generated/api.schemas'
import { wizardWorkspaceLabel } from './wizardRunDisplay'

const RUN_POLL_INTERVAL_MS = 10_000

export interface wizardRunsLogicValues {
    currentProjectId: number | null
    environment: RunEnvironmentEnumApi | 'all'
    filteredRuns: WizardRunApi[]
    hasRunFilters: boolean
    refreshingRuns: boolean
    runs: WizardRunApi[]
    runsFailed: boolean
    runsInitialLoading: boolean
    runsLoaded: boolean
    runsLoading: boolean
    search: string
    status: WizardRunApi['status'] | 'all'
}

export interface wizardRunsLogicActions {
    clearRunFilters: () => { value: true }
    loadRuns: () => { value: true }
    loadRunsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadRunsSuccess: (runs: WizardRunApi[]) => { runs: WizardRunApi[] }
    refreshRuns: () => { value: true }
    setEnvironment: (environment: RunEnvironmentEnumApi | 'all') => { environment: RunEnvironmentEnumApi | 'all' }
    setSearch: (search: string) => { search: string }
    setStatus: (status: WizardRunApi['status'] | 'all') => { status: WizardRunApi['status'] | 'all' }
}

export interface wizardRunsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        filteredRuns: (
            runs: WizardRunApi[],
            search: string,
            environment: RunEnvironmentEnumApi | 'all',
            status: WizardRunStatusEnumApi | 'all'
        ) => WizardRunApi[]
        hasRunFilters: (
            search: string,
            environment: RunEnvironmentEnumApi | 'all',
            status: WizardRunStatusEnumApi | 'all'
        ) => boolean
        runsInitialLoading: (runsLoaded: boolean) => boolean
    }
}

export type wizardRunsLogicType = MakeLogicType<
    wizardRunsLogicValues,
    wizardRunsLogicActions,
    Record<string, never>,
    wizardRunsLogicMeta
>

export const wizardRunsLogic = kea<wizardRunsLogicType>([
    path(['products', 'wizard', 'wizardRunsLogic']),
    connect(() => ({ values: [projectLogic, ['currentProjectId']] })),
    actions({
        refreshRuns: true,
        clearRunFilters: true,
        setSearch: (search: string) => ({ search }),
        setEnvironment: (environment: RunEnvironmentEnumApi | 'all') => ({ environment }),
        setStatus: (status: WizardRunApi['status'] | 'all') => ({ status }),
    }),
    reducers({
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
                clearRunFilters: () => '',
            },
        ],
        environment: [
            'all' as RunEnvironmentEnumApi | 'all',
            {
                setEnvironment: (_, { environment }) => environment,
                clearRunFilters: () => 'all',
            },
        ],
        status: [
            'all' as WizardRunApi['status'] | 'all',
            {
                setStatus: (_, { status }) => status,
                clearRunFilters: () => 'all',
            },
        ],
        runsLoaded: [
            false,
            {
                loadRunsSuccess: () => true,
                loadRunsFailure: () => true,
            },
        ],
        runsFailed: [
            false,
            {
                loadRuns: () => false,
                loadRunsFailure: () => true,
            },
        ],
        refreshingRuns: [
            false,
            {
                refreshRuns: () => true,
                loadRunsSuccess: () => false,
                loadRunsFailure: () => false,
            },
        ],
    }),
    loaders(({ values }) => ({
        runs: [
            [] as WizardRunApi[],
            {
                loadRuns: async () => {
                    if (!values.currentProjectId) {
                        return []
                    }

                    const response = await wizardRunsList(String(values.currentProjectId), { limit: 50, offset: 0 })

                    return response.results
                },
            },
        ],
    })),
    selectors({
        filteredRuns: [
            (s) => [s.runs, s.search, s.environment, s.status],
            (
                runs: WizardRunApi[],
                search: string,
                environment: RunEnvironmentEnumApi | 'all',
                status: WizardRunApi['status'] | 'all'
            ): WizardRunApi[] => {
                const searchText = search.trim().toLowerCase()

                return runs.filter((run) => {
                    const text = `${run.program.name} ${wizardWorkspaceLabel(run)} ${run.id}`.toLowerCase()

                    return (
                        text.includes(searchText) &&
                        (environment === 'all' || run.environment === environment) &&
                        (status === 'all' || run.status === status)
                    )
                })
            },
        ],
        hasRunFilters: [
            (s) => [s.search, s.environment, s.status],
            (
                search: string,
                environment: RunEnvironmentEnumApi | 'all',
                status: WizardRunApi['status'] | 'all'
            ): boolean => !!search.trim() || environment !== 'all' || status !== 'all',
        ],
        runsInitialLoading: [(s) => [s.runsLoaded], (runsLoaded: boolean): boolean => !runsLoaded],
    }),
    listeners(({ actions }) => ({
        refreshRuns: () => actions.loadRuns(),
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadRuns()

            cache.disposables.add(() => {
                const timerId = window.setInterval(() => actions.loadRuns(), RUN_POLL_INTERVAL_MS)

                return () => window.clearInterval(timerId)
            }, 'wizardRunPolling')
        },
    })),
])
