import { MakeLogicType, actions, events, kea, key, listeners, path, props, reducers } from 'kea'

import { getWizardRunsStreamRetrieveUrl, wizardRunsList } from '../generated/api'
import type { WizardRunApi, WizardRunTaskApi, WizardRunTaskListApi } from '../generated/api.schemas'
import { wizardRunIsActive } from '../wizardRunDisplay'

const ACTIVE_RUN_POLL_MS = 30_000
// ponytail: keep the FAB to five recent runs; the Wizard page lists the rest.
const ACTIVE_RUN_LIST_LIMIT = 5

type RunStreamState = Pick<
    WizardRunApi,
    'status' | 'stage' | 'error_code' | 'error_message' | 'updated_at' | 'started_at' | 'finished_at'
> &
    WizardRunTaskListApi

export interface wizardRunSyncLogicProps {
    projectId: string
}

export interface wizardRunSyncLogicValues {
    activeCount: number
    activeRuns: WizardRunApi[]
    closedRunIds: string[]
    dismissedRunIds: string[]
    run: WizardRunApi | null
    selectedRunId: string | null
    tasks: readonly WizardRunTaskApi[]
}

export interface wizardRunSyncLogicActions {
    checkActiveRuns: () => { value: true }
    activeRunsLoaded: (count: number, runs: WizardRunApi[]) => { count: number; runs: WizardRunApi[] }
    clearTasks: () => { value: true }
    runUpdated: (state: RunStreamState) => { state: RunStreamState }
    showRun: (run: WizardRunApi | null) => { run: WizardRunApi | null }
    selectRun: (run: WizardRunApi) => { run: WizardRunApi }
    connectRun: () => { value: true }
    closeRun: (runId: string) => { runId: string }
    dismissRun: (runId: string) => { runId: string }
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
        checkActiveRuns: true,
        activeRunsLoaded: (count: number, runs: WizardRunApi[]) => ({ count, runs }),
        clearTasks: true,
        runUpdated: (state: RunStreamState) => ({ state }),
        showRun: (run: WizardRunApi | null) => ({ run }),
        selectRun: (run: WizardRunApi) => ({ run }),
        connectRun: true,
        closeRun: (runId: string) => ({ runId }),
        dismissRun: (runId: string) => ({ runId }),
    }),
    reducers({
        activeCount: [0, { activeRunsLoaded: (_, { count }) => count }],
        activeRuns: [[] as WizardRunApi[], { activeRunsLoaded: (_, { runs }) => runs }],
        closedRunIds: [[] as string[], { closeRun: (current, { runId }) => [...current, runId] }],
        dismissedRunIds: [
            [] as string[],
            { persist: true },
            { dismissRun: (current, { runId }) => (current.includes(runId) ? current : [...current, runId]) },
        ],
        selectedRunId: [
            null as string | null,
            {
                activeRunsLoaded: (current, { runs }) =>
                    current && runs.some((run) => run.id === current) ? current : null,
                selectRun: (_, { run }) => run.id,
                closeRun: (current, { runId }) => (current === runId ? null : current),
                dismissRun: (current, { runId }) => (current === runId ? null : current),
            },
        ],
        run: [
            null as WizardRunApi | null,
            {
                showRun: (_, { run }) => run,
                selectRun: (_, { run }) => run,
                runUpdated: (current, { state }) => (current ? { ...current, ...state } : null),
                closeRun: () => null,
                dismissRun: () => null,
            },
        ],
        tasks: [
            [] as readonly WizardRunTaskApi[],
            {
                clearTasks: () => [],
                showRun: () => [],
                selectRun: () => [],
                runUpdated: (_, { state }) => state.tasks,
                closeRun: () => [],
                dismissRun: () => [],
            },
        ],
    }),
    listeners(({ actions, cache, props: logicProps, values }) => ({
        checkActiveRuns: async () => {
            if (cache.checking) {
                return
            }
            cache.checking = true
            try {
                const page = await wizardRunsList(logicProps.projectId, {
                    status: ['created', 'running'],
                    limit: ACTIVE_RUN_LIST_LIMIT,
                })
                actions.activeRunsLoaded(page.count, page.results)
            } catch {
                return
            } finally {
                cache.checking = false
            }
        },
        activeRunsLoaded: () => {
            const visibleRuns = values.activeRuns.filter(
                (run) => !values.closedRunIds.includes(run.id) && !values.dismissedRunIds.includes(run.id)
            )
            const nextRun =
                visibleRuns.find((run) => run.id === values.selectedRunId) ??
                visibleRuns[0] ??
                (values.run && !wizardRunIsActive(values.run) ? values.run : null)
            if (nextRun?.id !== values.run?.id) {
                actions.showRun(nextRun)
            }
            actions.connectRun()
        },
        selectRun: () => {
            actions.connectRun()
        },
        connectRun: () => {
            const run = values.run
            if (
                !run ||
                values.closedRunIds.includes(run.id) ||
                values.dismissedRunIds.includes(run.id) ||
                !wizardRunIsActive(run)
            ) {
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
                            actions.checkActiveRuns()
                        }
                    } catch {
                        actions.checkActiveRuns()
                    }
                }
                return () => stream.close()
            }, 'run-stream')
        },
        closeRun: () => {
            cache.disposables.dispose('run-stream')
            cache.connectedRunId = undefined
            actions.activeRunsLoaded(values.activeCount, values.activeRuns)
        },
        dismissRun: () => {
            cache.disposables.dispose('run-stream')
            cache.connectedRunId = undefined
            actions.activeRunsLoaded(values.activeCount, values.activeRuns)
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.checkActiveRuns()
            cache.disposables.add(() => {
                const timer = window.setInterval(() => actions.checkActiveRuns(), ACTIVE_RUN_POLL_MS)
                return () => window.clearInterval(timer)
            }, 'active-run-poll')
        },
    })),
])
