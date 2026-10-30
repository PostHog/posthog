import { MakeLogicType, actions, events, kea, key, listeners, path, props, reducers } from 'kea'

import { getWizardRunsStreamRetrieveUrl, wizardRunsList } from '../generated/api'
import type { WizardRunApi, WizardRunTaskApi, WizardRunTaskListApi } from '../generated/api.schemas'
import { wizardRunIsActive } from '../wizardRunDisplay'

const RUN_POLL_MS = 30_000

// Runs created before this are never synced, so older history does not open streams.
const RUN_VISIBLE_AFTER = '2026-09-28T00:00:00Z'

const RUN_LIST_LIMIT = 5

type RunStreamState = Pick<
    WizardRunApi,
    'status' | 'stage' | 'error_code' | 'error_message' | 'updated_at' | 'started_at' | 'finished_at'
> &
    WizardRunTaskListApi

export interface wizardRunSyncLogicProps {
    projectId: string
}

export interface wizardRunSyncLogicValues {
    runs: WizardRunApi[]
    run: WizardRunApi | null
    tasks: readonly WizardRunTaskApi[]
}

export interface wizardRunSyncLogicActions {
    checkRuns: () => { value: true }
    runsLoaded: (runs: WizardRunApi[]) => { runs: WizardRunApi[] }
    clearTasks: () => { value: true }
    runUpdated: (state: RunStreamState) => { state: RunStreamState }
    showRun: (run: WizardRunApi | null) => { run: WizardRunApi | null }
    connectRun: () => { value: true }
}

export type wizardRunSyncLogicType = MakeLogicType<
    wizardRunSyncLogicValues,
    wizardRunSyncLogicActions,
    wizardRunSyncLogicProps
>

export const wizardRunSyncLogic = kea<wizardRunSyncLogicType>([
    path(['products', 'wizard', 'wizardRunSyncLogic']),
    props({} as wizardRunSyncLogicProps),
    key((logicProps) => logicProps.projectId),
    actions({
        checkRuns: true,
        runsLoaded: (runs: WizardRunApi[]) => ({ runs }),
        clearTasks: true,
        runUpdated: (state: RunStreamState) => ({ state }),
        showRun: (run: WizardRunApi | null) => ({ run }),
        connectRun: true,
    }),
    reducers({
        runs: [[] as WizardRunApi[], { runsLoaded: (_, { runs }) => runs }],
        run: [
            null as WizardRunApi | null,
            {
                runsLoaded: (current, { runs }) =>
                    current ? (runs.find((run) => run.id === current.id) ?? current) : null,
                showRun: (_, { run }) => run,
                runUpdated: (current, { state }) => (current ? { ...current, ...state } : null),
            },
        ],
        tasks: [
            [] as readonly WizardRunTaskApi[],
            {
                clearTasks: () => [],
                showRun: () => [],
                runUpdated: (_, { state }) => state.tasks,
            },
        ],
    }),
    listeners(({ actions, cache, props: logicProps, values }) => ({
        checkRuns: async () => {
            if (cache.checking) {
                return
            }
            cache.checking = true
            try {
                const [activePage, recentPage] = await Promise.all([
                    wizardRunsList(logicProps.projectId, {
                        status: ['created', 'running'],
                        created_after: RUN_VISIBLE_AFTER,
                        limit: RUN_LIST_LIMIT,
                    }),
                    wizardRunsList(logicProps.projectId, {
                        created_after: RUN_VISIBLE_AFTER,
                        limit: RUN_LIST_LIMIT,
                    }),
                ])
                const activeRuns = activePage.results
                    .map((run) => recentPage.results.find((recentRun) => recentRun.id === run.id) ?? run)
                    .filter(wizardRunIsActive)
                actions.runsLoaded([
                    ...activeRuns,
                    ...recentPage.results.filter((run) => !activeRuns.some((activeRun) => activeRun.id === run.id)),
                ])
            } catch {
                return
            } finally {
                cache.checking = false
            }
        },
        runsLoaded: () => {
            const nextRun = values.runs[0] ?? (values.run && !wizardRunIsActive(values.run) ? values.run : null)
            if (nextRun?.id !== values.run?.id) {
                actions.showRun(nextRun)
            }
            actions.connectRun()
        },
        connectRun: () => {
            const run = values.run
            if (!run || !wizardRunIsActive(run)) {
                cache.disposables.dispose('run-stream')
                cache.connectedRunId = undefined
                return
            }
            if (cache.connectedRunId === run.id) {
                return
            }
            cache.disposables.dispose('run-stream')
            cache.connectedRunId = run.id
            actions.clearTasks()
            cache.disposables.add(() => {
                const stream = new EventSource(getWizardRunsStreamRetrieveUrl(logicProps.projectId, run.id), {
                    withCredentials: true,
                })
                stream.onmessage = (event: MessageEvent<string>): void => {
                    try {
                        const state = JSON.parse(event.data) as RunStreamState
                        actions.runUpdated(state)
                        if (!wizardRunIsActive({ ...run, ...state })) {
                            actions.checkRuns()
                        }
                    } catch {
                        actions.checkRuns()
                    }
                }
                return () => stream.close()
            }, 'run-stream')
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.checkRuns()
            cache.disposables.add(() => {
                const timer = window.setInterval(() => actions.checkRuns(), RUN_POLL_MS)
                return () => window.clearInterval(timer)
            }, 'active-run-poll')
        },
    })),
])
