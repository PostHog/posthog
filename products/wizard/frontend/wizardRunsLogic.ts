import { MakeLogicType, actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
import { projectLogic } from 'scenes/projectLogic'

import { wizardRunsList } from './generated/api'
import type { RunEnvironmentEnumApi, WizardRunApi, WizardRunStatusEnumApi } from './generated/api.schemas'
import { wizardWorkspaceLabel } from './wizardRunDisplay'

const RUN_POLL_INTERVAL_MS = 10_000
const RUN_PAGE_SIZE = 100

export interface wizardRunsLogicValues {
    currentProjectId: number | null
    environment: RunEnvironmentEnumApi | 'all'
    filteredRuns: WizardRunApi[]
    hasRunFilters: boolean
    refreshingRuns: boolean
    runs: WizardRunApi[]
    runsFailed: boolean
    runsInitialLoading: boolean
    runsLastLoadedAt: string | null
    runsLoaded: boolean
    runsLoading: boolean
    search: string
    status: WizardRunApi['status'] | 'all'
}

export interface wizardRunsLogicActions {
    clearRunFilters: () => { value: true }
    loadRuns: (payload?: { poll?: boolean }) => { poll?: boolean }
    loadRunsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadRunsSuccess: (runs: WizardRunApi[]) => { runs: WizardRunApi[] }
    refreshRuns: () => { value: true }
    scheduleNextRunPoll: () => { value: true }
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
        runsInitialLoading: (runsLoaded: boolean, runsLoading: boolean, runs: WizardRunApi[]) => boolean
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
        scheduleNextRunPoll: true,
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
        runsLastLoadedAt: [
            null as string | null,
            {
                loadRunsSuccess: () => dayjs().toISOString(),
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
                loadRuns: async ({ poll = false }: { poll?: boolean } = {}, breakpoint) => {
                    if (!values.currentProjectId) {
                        return []
                    }

                    try {
                        if (poll) {
                            // Background polls fetch only the newest page and merge it into the
                            // cached list, so cost stays flat as the run history grows.
                            const response = await wizardRunsList(String(values.currentProjectId), {
                                limit: RUN_PAGE_SIZE,
                                offset: 0,
                            })
                            await breakpoint()

                            const freshIds = new Set(response.results.map((run) => run.id))

                            return [...response.results, ...values.runs.filter((run) => !freshIds.has(run.id))]
                        }

                        const runs: WizardRunApi[] = []
                        let offset = 0

                        while (true) {
                            const response = await wizardRunsList(String(values.currentProjectId), {
                                limit: RUN_PAGE_SIZE,
                                offset,
                            })
                            breakpoint()
                            runs.push(...response.results)

                            if (!response.next) {
                                return runs
                            }

                            offset += RUN_PAGE_SIZE
                        }
                    } catch (error) {
                        // A superseded request must not report failure against newer data.
                        await breakpoint()
                        throw error
                    }
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
        runsInitialLoading: [
            (s) => [s.runsLoaded, s.runsLoading, s.runs],
            (runsLoaded: boolean, runsLoading: boolean, runs: WizardRunApi[]): boolean =>
                !runsLoaded || (runsLoading && runs.length === 0),
        ],
    }),
    listeners(({ actions, cache }) => ({
        refreshRuns: () => actions.loadRuns({ poll: false }),
        loadRunsSuccess: () => actions.scheduleNextRunPoll(),
        loadRunsFailure: () => actions.scheduleNextRunPoll(),
        // Each poll starts only after the previous load settles, so a slow load can never be
        // cut short by the next tick.
        scheduleNextRunPoll: () => {
            cache.disposables.add(() => {
                const timerId = window.setTimeout(() => actions.loadRuns({ poll: true }), RUN_POLL_INTERVAL_MS)

                return () => window.clearTimeout(timerId)
            }, 'wizardRunPolling')
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadRuns({ poll: false })
        },
    })),
])
