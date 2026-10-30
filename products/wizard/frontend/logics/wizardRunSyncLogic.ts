import {
    LogicWrapper,
    MakeLogicType,
    actions,
    connect,
    events,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'

import { userLogic } from 'scenes/userLogic'

import type { UserType } from '~/types'

import {
    getWizardRunsStreamRetrieveUrl,
    wizardRunsList,
    wizardRunsRetrieve,
    wizardRunsTasksRetrieve,
} from '../generated/api'
import type {
    WizardRunApi,
    WizardRunArtifactApi,
    WizardRunTaskApi,
    WizardRunTaskListApi,
} from '../generated/api.schemas'
import { loadWizardRunArtifacts } from '../lib/wizardApi'
import { wizardRunIsActive } from '../lib/wizardRunDisplay'

const RUN_POLL_MS = 30_000
const RUN_DISCOVERY_POLL_MS = 5_000

const RUN_LIST_LIMIT = 100
// Leave HTTP/1.1 connections available for requests and other app streams.
const MAX_RUN_STREAMS = 1

type RunStreamState = Pick<
    WizardRunApi,
    'status' | 'stage' | 'error_code' | 'error_message' | 'updated_at' | 'started_at' | 'finished_at'
> &
    WizardRunTaskListApi

function streamRunPatch(state: RunStreamState): Partial<WizardRunApi> {
    return {
        status: state.status,
        stage: state.stage,
        error_code: state.error_code,
        error_message: state.error_message,
        updated_at: state.updated_at,
        started_at: state.started_at,
        finished_at: state.finished_at,
    }
}

export interface wizardRunSyncLogicProps {
    projectId: string
}

export interface wizardRunSyncLogicValues {
    user: UserType | null
    runs: WizardRunApi[]
    userRuns: WizardRunApi[]
    activeUserRuns: WizardRunApi[]
    watchedRunIds: Record<string, string[]>
    activeWatchedRuns: WizardRunApi[]
    tasksByRunId: Record<string, readonly WizardRunTaskApi[]>
    artifactsByRunId: Record<string, WizardRunArtifactApi[]>
    runDataLoading: Record<string, boolean>
    runDataErrors: Record<string, string | null>
}

export interface wizardRunSyncLogicActions {
    checkRuns: (recentOnly?: boolean) => { recentOnly: boolean }
    runsLoaded: (runs: WizardRunApi[], merge?: boolean) => { runs: WizardRunApi[]; merge: boolean }
    runUpdated: (runId: string, state: RunStreamState) => { runId: string; state: RunStreamState }
    loadRunData: (run: WizardRunApi) => { run: WizardRunApi }
    tasksLoaded: (
        runId: string,
        tasks: readonly WizardRunTaskApi[]
    ) => { runId: string; tasks: readonly WizardRunTaskApi[] }
    runDataLoaded: (
        runId: string,
        artifacts: WizardRunArtifactApi[]
    ) => {
        runId: string
        artifacts: WizardRunArtifactApi[]
    }
    runDataStarted: (runId: string) => { runId: string }
    runDataFailed: (runId: string) => { runId: string }
    connectRuns: () => { value: true }
    watchRuns: (source: string, runIds: string[]) => { source: string; runIds: string[] }
    refreshWatchedRun: () => { value: true }
}

export type wizardRunSyncLogicType = MakeLogicType<
    wizardRunSyncLogicValues,
    wizardRunSyncLogicActions,
    wizardRunSyncLogicProps
>

export const wizardRunSyncLogic: LogicWrapper<wizardRunSyncLogicType> = kea<wizardRunSyncLogicType>([
    props({} as wizardRunSyncLogicProps),
    key((logicProps) => logicProps.projectId),
    path((key) => ['products', 'wizard', 'wizardRunSyncLogic', key]),
    connect(() => ({ values: [userLogic, ['user']] })),
    actions({
        checkRuns: (recentOnly = false) => ({ recentOnly }),
        runsLoaded: (runs: WizardRunApi[], merge = false) => ({ runs, merge }),
        runUpdated: (runId: string, state: RunStreamState) => ({ runId, state }),
        loadRunData: (run: WizardRunApi) => ({ run }),
        tasksLoaded: (runId: string, tasks: readonly WizardRunTaskApi[]) => ({ runId, tasks }),
        runDataLoaded: (runId: string, artifacts: WizardRunArtifactApi[]) => ({ runId, artifacts }),
        runDataStarted: (runId: string) => ({ runId }),
        runDataFailed: (runId: string) => ({ runId }),
        connectRuns: true,
        watchRuns: (source: string, runIds: string[]) => ({ source, runIds }),
        refreshWatchedRun: true,
    }),
    reducers({
        watchedRunIds: [
            {} as Record<string, string[]>,
            { watchRuns: (state, { source, runIds }) => ({ ...state, [source]: runIds }) },
        ],
        runs: [
            [] as WizardRunApi[],
            {
                runsLoaded: (current, { runs, merge }) => {
                    const currentRuns = new Map(current.map((run) => [run.id, run]))
                    const incomingIds = new Set(runs.map((run) => run.id))
                    const nextRuns = merge ? [...runs, ...current.filter((run) => !incomingIds.has(run.id))] : runs
                    return nextRuns.map((run) => {
                        const streamedRun = currentRuns.get(run.id)
                        return streamedRun &&
                            Date.parse(streamedRun.updated_at ?? streamedRun.created_at) >
                                Date.parse(run.updated_at ?? run.created_at)
                            ? streamedRun
                            : run
                    })
                },
                runUpdated: (current, { runId, state }) =>
                    current.map((run) => (run.id === runId ? { ...run, ...streamRunPatch(state) } : run)),
            },
        ],
        tasksByRunId: [
            {} as Record<string, readonly WizardRunTaskApi[]>,
            {
                runUpdated: (current, { runId, state }) => ({ ...current, [runId]: state.tasks }),
                tasksLoaded: (current, { runId, tasks }) => ({ ...current, [runId]: tasks }),
            },
        ],
        artifactsByRunId: [
            {} as Record<string, WizardRunArtifactApi[]>,
            {
                runDataLoaded: (current, { runId, artifacts }) => ({ ...current, [runId]: artifacts }),
            },
        ],
        runDataLoading: [
            {} as Record<string, boolean>,
            {
                runDataStarted: (state, { runId }) => ({ ...state, [runId]: true }),
                runDataLoaded: (state, { runId }) => ({ ...state, [runId]: false }),
                runDataFailed: (state, { runId }) => ({ ...state, [runId]: false }),
            },
        ],
        runDataErrors: [
            {} as Record<string, string | null>,
            {
                runDataStarted: (state, { runId }) => ({ ...state, [runId]: null }),
                runDataFailed: (state, { runId }) => ({
                    ...state,
                    [runId]: "Couldn't load tasks and artifacts. Try again.",
                }),
            },
        ],
    }),
    selectors({
        userRuns: [
            (s) => [s.runs, s.user],
            (runs: WizardRunApi[], user: UserType | null): WizardRunApi[] =>
                user ? runs.filter((run) => run.created_by_id === user.id) : [],
        ],
        activeUserRuns: [(s) => [s.userRuns], (runs: WizardRunApi[]): WizardRunApi[] => runs.filter(wizardRunIsActive)],
        activeWatchedRuns: [
            (s) => [s.runs, s.watchedRunIds],
            (runs: WizardRunApi[], watched: Record<string, string[]>): WizardRunApi[] => {
                const runsById = new Map(runs.map((run) => [run.id, run]))
                return [...new Set(Object.values(watched).reverse().flat())]
                    .map((id) => runsById.get(id))
                    .filter((run): run is WizardRunApi => !!run && wizardRunIsActive(run))
            },
        ],
    }),
    listeners(({ actions, cache, props: logicProps, values }) => ({
        checkRuns: async ({ recentOnly }) => {
            if (cache.checking || !logicProps.projectId || !values.user) {
                return
            }
            cache.checking = true
            const disposables = cache.disposables
            const knownRunIds = new Set(values.runs.map((run) => run.id))
            try {
                const runs: WizardRunApi[] = []
                let offset = 0
                while (true) {
                    const page = await wizardRunsList(logicProps.projectId, {
                        limit: RUN_LIST_LIMIT,
                        offset,
                    })
                    if (disposables.isDisposed) {
                        return
                    }
                    runs.push(...page.results)
                    if (recentOnly || !page.next) {
                        break
                    }
                    offset += RUN_LIST_LIMIT
                }
                // A Library creation response can arrive after this poll started but before its older snapshot.
                const concurrentRuns = values.runs.filter((run) => !knownRunIds.has(run.id))
                actions.runsLoaded(
                    [...new Map([...concurrentRuns, ...runs].map((run) => [run.id, run])).values()],
                    recentOnly
                )
                if (!recentOnly) {
                    cache.historyLoaded = true
                }
            } catch {
                return
            } finally {
                cache.checking = false
            }
        },
        runsLoaded: () => {
            actions.connectRuns()
            for (const run of values.runs) {
                if (!wizardRunIsActive(run) && values.runDataLoading[run.id] !== undefined) {
                    actions.loadRunData(run)
                }
            }
        },
        watchRuns: () => actions.connectRuns(),
        [userLogic.actionTypes.loadUserSuccess]: () => {
            actions.connectRuns()
            actions.checkRuns(!!cache.historyLoaded)
        },
        runUpdated: ({ runId }) => {
            actions.connectRuns()
            const run = values.runs.find((run) => run.id === runId)
            if (run && !wizardRunIsActive(run)) {
                actions.checkRuns(true)
                if (values.runDataLoading[run.id] !== undefined) {
                    actions.loadRunData(run)
                }
            }
        },
        loadRunData: async ({ run }) => {
            if (run.team_id !== Number(logicProps.projectId)) {
                return
            }
            if (!values.runs.some((knownRun) => knownRun.id === run.id)) {
                actions.runsLoaded([run], true)
            }
            const version = wizardRunIsActive(run) ? 'active' : `${run.status}:${run.updated_at}`
            if (cache.runDataVersions[run.id] === version || cache.runDataRequests[run.id]?.version === version) {
                return
            }
            const request = { version }
            cache.runDataRequests[run.id] = request
            const disposables = cache.disposables
            const isCurrentRequest = (): boolean => !disposables.isDisposed && cache.runDataRequests[run.id] === request
            const previousTasks = values.tasksByRunId[run.id]
            actions.runDataStarted(run.id)
            try {
                const [snapshot, artifacts] = await Promise.all([
                    wizardRunsTasksRetrieve(logicProps.projectId, run.id),
                    loadWizardRunArtifacts(logicProps.projectId, run.id),
                ])
                if (!isCurrentRequest()) {
                    return
                }
                // A task snapshot requested before an SSE update must not overwrite that newer update.
                if (values.tasksByRunId[run.id] === previousTasks) {
                    actions.tasksLoaded(run.id, snapshot.tasks)
                }
                cache.runDataVersions[run.id] = version
                actions.runDataLoaded(run.id, artifacts)
            } catch {
                if (isCurrentRequest()) {
                    actions.runDataFailed(run.id)
                }
            } finally {
                if (cache.runDataRequests[run.id] === request) {
                    delete cache.runDataRequests[run.id]
                }
            }
        },
        refreshWatchedRun: async () => {
            if (cache.refreshingWatchedRun || !values.activeWatchedRuns.length) {
                return
            }
            const run = values.activeWatchedRuns[(cache.nextRunIndex ?? 0) % values.activeWatchedRuns.length]
            cache.nextRunIndex = (cache.nextRunIndex ?? 0) + 1
            cache.refreshingWatchedRun = true
            const disposables = cache.disposables
            const previousTasks = values.tasksByRunId[run.id]
            try {
                const [latest, snapshot] = await Promise.all([
                    wizardRunsRetrieve(logicProps.projectId, run.id),
                    wizardRunsTasksRetrieve(logicProps.projectId, run.id),
                ])
                if (disposables.isDisposed) {
                    return
                }
                actions.runsLoaded([latest], true)
                if (values.tasksByRunId[run.id] === previousTasks) {
                    actions.tasksLoaded(run.id, snapshot.tasks)
                }
            } catch {
                // Discovery and streams can still update the run while its fallback request fails.
            } finally {
                cache.refreshingWatchedRun = false
            }
        },
        connectRuns: () => {
            const streamedRuns = values.activeWatchedRuns.slice(0, MAX_RUN_STREAMS)
            const activeRunIds = streamedRuns.map((run) => run.id)
            const connectedRunIds: string[] = cache.connectedRunIds ?? []

            for (const runId of connectedRunIds) {
                if (!activeRunIds.includes(runId)) {
                    cache.disposables.dispose(`run-stream:${runId}`)
                }
            }
            cache.connectedRunIds = activeRunIds

            for (const run of streamedRuns) {
                if (connectedRunIds.includes(run.id)) {
                    continue
                }
                cache.disposables.add(() => {
                    const stream = new EventSource(getWizardRunsStreamRetrieveUrl(logicProps.projectId, run.id), {
                        withCredentials: true,
                    })
                    stream.onmessage = (event: MessageEvent<string>): void => {
                        try {
                            const state = JSON.parse(event.data) as RunStreamState
                            actions.runUpdated(run.id, state)
                        } catch {
                            actions.checkRuns(true)
                        }
                    }
                    return () => stream.close()
                }, `run-stream:${run.id}`)
            }
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            cache.runDataVersions = {}
            cache.runDataRequests = {}
            actions.checkRuns()
            cache.disposables.add(() => {
                const timer = window.setInterval(() => actions.refreshWatchedRun(), RUN_POLL_MS)
                return () => window.clearInterval(timer)
            }, 'active-run-poll')
            cache.disposables.add(() => {
                const discoverRuns = (): void => actions.checkRuns(true)
                const timer = window.setInterval(discoverRuns, RUN_DISCOVERY_POLL_MS)
                window.addEventListener('focus', discoverRuns)
                discoverRuns()
                return () => {
                    window.clearInterval(timer)
                    window.removeEventListener('focus', discoverRuns)
                }
            }, 'run-discovery-poll')
        },
    })),
])
