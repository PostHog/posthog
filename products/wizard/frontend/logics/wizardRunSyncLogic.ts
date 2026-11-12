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

import { ApiError } from 'lib/api-error'
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
// Discovery only finds runs started outside this tab (the CLI). Streams and refreshWatchedRun cover active runs,
// so it can be slow: a user with no runs is checked on focus only, a user with runs once a minute. A view that
// is waiting for a CLI run to appear (onboarding) opts into the fast tick with awaitRuns.
const RUN_DISCOVERY_TICK_MS = 5_000
const RUN_DISCOVERY_POLL_MS = 60_000
const RUN_DISCOVERY_MIN_GAP_MS = 30_000

const RUN_LIST_LIMIT = 100
// Leave HTTP/1.1 connections available for requests and other app streams.
const MAX_RUN_STREAMS = 1

type RunStreamState = Pick<
    WizardRunApi,
    'status' | 'stage' | 'error_code' | 'error_message' | 'updated_at' | 'started_at' | 'finished_at'
> &
    WizardRunTaskListApi

function checkRunsRetryDelayMs(error: unknown): number {
    const retryAfterSeconds = error instanceof ApiError ? Number(error.headers?.get('Retry-After')) : NaN
    return retryAfterSeconds > 0 ? retryAfterSeconds * 1000 : RUN_POLL_MS
}

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

interface WizardRunDataOptions {
    tasksOnly?: boolean
    force?: boolean
}

export interface wizardRunSyncLogicValues {
    user: UserType | null
    runs: WizardRunApi[]
    userRuns: WizardRunApi[]
    activeUserRuns: WizardRunApi[]
    watchedRunIds: Record<string, string[]>
    awaitingRunSources: Record<string, boolean>
    awaitingRuns: boolean
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
    loadRunData: (
        run: WizardRunApi,
        options?: WizardRunDataOptions
    ) => { run: WizardRunApi; options: WizardRunDataOptions }
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
    awaitRuns: (source: string, waiting: boolean) => { source: string; waiting: boolean }
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
        loadRunData: (run: WizardRunApi, options: WizardRunDataOptions = {}) => ({ run, options }),
        tasksLoaded: (runId: string, tasks: readonly WizardRunTaskApi[]) => ({ runId, tasks }),
        runDataLoaded: (runId: string, artifacts: WizardRunArtifactApi[]) => ({ runId, artifacts }),
        runDataStarted: (runId: string) => ({ runId }),
        runDataFailed: (runId: string) => ({ runId }),
        connectRuns: true,
        watchRuns: (source: string, runIds: string[]) => ({ source, runIds }),
        awaitRuns: (source: string, waiting: boolean) => ({ source, waiting }),
        refreshWatchedRun: true,
    }),
    reducers({
        watchedRunIds: [
            {} as Record<string, string[]>,
            { watchRuns: (state, { source, runIds }) => ({ ...state, [source]: runIds }) },
        ],
        awaitingRunSources: [
            {} as Record<string, boolean>,
            { awaitRuns: (state, { source, waiting }) => ({ ...state, [source]: waiting }) },
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
        awaitingRuns: [
            (s) => [s.awaitingRunSources],
            (sources: Record<string, boolean>): boolean => Object.values(sources).some(Boolean),
        ],
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
            // Focus, stream updates and user reloads all call this, so only a shared cooldown keeps
            // them from retrying a throttled list request back to back.
            if (cache.checking || !logicProps.projectId || !values.user || Date.now() < cache.checkRunsBlockedUntil) {
                return
            }
            cache.checking = true
            cache.lastCheckStartedAt = Date.now()
            const disposables = cache.disposables
            const knownRunIds = new Set(values.runs.map((run) => run.id))
            try {
                const runs: WizardRunApi[] = []
                let offset = 0
                while (true) {
                    const page = await wizardRunsList(logicProps.projectId, {
                        created_by_id: values.user.id,
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
            } catch (error) {
                cache.checkRunsBlockedUntil = Date.now() + checkRunsRetryDelayMs(error)
                return
            } finally {
                cache.checking = false
            }
        },
        runsLoaded: () => actions.connectRuns(),
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
            }
        },
        loadRunData: async ({ run, options }) => {
            if (run.team_id !== Number(logicProps.projectId)) {
                return
            }
            if (!values.runs.some((knownRun) => knownRun.id === run.id)) {
                actions.runsLoaded([run], true)
            }
            const stateVersion = wizardRunIsActive(run) ? 'active' : `${run.status}:${run.updated_at}`
            const version = options.tasksOnly ? `tasks:${stateVersion}` : stateVersion
            if (cache.runDataVersions[run.id] === version || cache.runDataRequests[run.id]?.version === version) {
                return
            }
            const failure = cache.runDataFailures[run.id]
            if (!options.force && failure?.version === version && failure.retryAfter > Date.now()) {
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
                    options.tasksOnly
                        ? Promise.resolve(values.artifactsByRunId[run.id] ?? [])
                        : loadWizardRunArtifacts(logicProps.projectId, run.id),
                ])
                if (!isCurrentRequest()) {
                    return
                }
                // A task snapshot requested before an SSE update must not overwrite that newer update.
                if (values.tasksByRunId[run.id] === previousTasks) {
                    actions.tasksLoaded(run.id, snapshot.tasks)
                }
                cache.runDataVersions[run.id] = version
                delete cache.runDataFailures[run.id]
                actions.runDataLoaded(run.id, artifacts)
            } catch {
                if (isCurrentRequest()) {
                    cache.runDataFailures[run.id] = { version, retryAfter: Date.now() + RUN_POLL_MS }
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
            // A created run has no worker yet, so its stream would sit idle. refreshWatchedRun picks up the transition.
            const streamedRuns = values.activeWatchedRuns
                .filter((run) => run.status === 'running')
                .slice(0, MAX_RUN_STREAMS)
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
    events(({ actions, cache, values }) => ({
        afterMount: () => {
            cache.runDataVersions = {}
            cache.runDataRequests = {}
            cache.runDataFailures = {}
            cache.checkRunsBlockedUntil = 0
            cache.lastCheckStartedAt = 0
            actions.checkRuns()
            cache.disposables.add(() => {
                const timer = window.setInterval(() => actions.refreshWatchedRun(), RUN_POLL_MS)
                return () => window.clearInterval(timer)
            }, 'active-run-poll')
            cache.disposables.add(() => {
                const discoverRuns = (minGapMs: number, recentOnly = true): void => {
                    if (Date.now() - cache.lastCheckStartedAt >= minGapMs) {
                        actions.checkRuns(recentOnly)
                    }
                }
                const onFocus = (): void => discoverRuns(RUN_DISCOVERY_MIN_GAP_MS)
                const timer = window.setInterval(() => {
                    if (values.awaitingRuns) {
                        discoverRuns(0)
                    } else if (!cache.historyLoaded) {
                        // Until one full list succeeds, an empty userRuns only means the first request failed.
                        discoverRuns(RUN_DISCOVERY_POLL_MS, false)
                    } else if (values.userRuns.length) {
                        discoverRuns(RUN_DISCOVERY_POLL_MS)
                    }
                }, RUN_DISCOVERY_TICK_MS)
                window.addEventListener('focus', onFocus)
                // The disposable re-runs this setup when a hidden tab becomes visible, which is the catch-up check.
                onFocus()
                return () => {
                    window.clearInterval(timer)
                    window.removeEventListener('focus', onFocus)
                }
            }, 'run-discovery-poll')
        },
    })),
])
