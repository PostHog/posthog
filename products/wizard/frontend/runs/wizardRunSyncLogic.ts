import { MakeLogicType, actions, events, kea, key, listeners, path, props, reducers } from 'kea'

import { getWizardRunsStreamRetrieveUrl, wizardRunsList } from '../generated/api'
import type { WizardRunApi, WizardRunTaskApi, WizardRunTaskListApi } from '../generated/api.schemas'
import { wizardRunIsActive } from '../wizardRunDisplay'

const ACTIVE_RUN_POLL_MS = 30_000

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
    run: WizardRunApi | null
    tasks: readonly WizardRunTaskApi[]
}

export interface wizardRunSyncLogicActions {
    checkActiveRuns: () => { value: true }
    activeRunsLoaded: (count: number, run: WizardRunApi | null) => { count: number; run: WizardRunApi | null }
    clearTasks: () => { value: true }
    runUpdated: (state: RunStreamState) => { state: RunStreamState }
    dismissRun: () => { value: true }
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
        activeRunsLoaded: (count: number, run: WizardRunApi | null) => ({ count, run }),
        clearTasks: true,
        runUpdated: (state: RunStreamState) => ({ state }),
        dismissRun: true,
    }),
    reducers({
        activeCount: [0, { activeRunsLoaded: (_, { count }) => count }],
        run: [
            null as WizardRunApi | null,
            {
                activeRunsLoaded: (current, { run }) =>
                    run
                        ? current?.id === run.id
                            ? current
                            : run
                        : current && !wizardRunIsActive(current)
                          ? current
                          : null,
                runUpdated: (current, { state }) => (current ? { ...current, ...state } : null),
                dismissRun: () => null,
            },
        ],
        tasks: [
            [] as readonly WizardRunTaskApi[],
            {
                clearTasks: () => [],
                runUpdated: (_, { state }) => state.tasks,
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
                const page = await wizardRunsList(logicProps.projectId, { status: ['created', 'running'], limit: 1 })
                actions.activeRunsLoaded(page.count, page.results[0] ?? null)
            } catch {
                return
            } finally {
                cache.checking = false
            }
        },
        activeRunsLoaded: () => {
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
                            actions.checkActiveRuns()
                        }
                    } catch {
                        actions.checkActiveRuns()
                    }
                }
                return () => stream.close()
            }, 'run-stream')
        },
        dismissRun: () => {
            cache.disposables.dispose('run-stream')
            cache.connectedRunId = undefined
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
