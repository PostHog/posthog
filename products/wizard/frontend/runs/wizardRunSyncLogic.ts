import { MakeLogicType, actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { getWizardRunsStreamRetrieveUrl, wizardRunsList } from '../generated/api'
import type { WizardRunApi, WizardRunTaskApi, WizardRunTaskListApi } from '../generated/api.schemas'
import { wizardRunIsActive } from '../wizardRunDisplay'

const RUN_POLL_MS = 30_000
// ponytail: show five active and five completed runs; the Wizard page lists the rest.
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
    activeCount: number
    runs: WizardRunApi[]
    visibleRuns: WizardRunApi[]
    closedRunIds: string[]
    dismissedRunIds: string[]
    run: WizardRunApi | null
    selectedRunId: string | null
    tasks: readonly WizardRunTaskApi[]
}

export interface wizardRunSyncLogicActions {
    checkRuns: () => { value: true }
    runsLoaded: (count: number, runs: WizardRunApi[]) => { count: number; runs: WizardRunApi[] }
    clearTasks: () => { value: true }
    runUpdated: (state: RunStreamState) => { state: RunStreamState }
    showRun: (run: WizardRunApi | null) => { run: WizardRunApi | null }
    selectRun: (run: WizardRunApi) => { run: WizardRunApi }
    connectRun: () => { value: true }
    closeRun: (runId: string) => { runId: string }
    dismissRun: (runId: string) => { runId: string }
    expandFab: (runsCount: number) => { runsCount: number }
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
        runsLoaded: (count: number, runs: WizardRunApi[]) => ({ count, runs }),
        clearTasks: true,
        runUpdated: (state: RunStreamState) => ({ state }),
        showRun: (run: WizardRunApi | null) => ({ run }),
        selectRun: (run: WizardRunApi) => ({ run }),
        connectRun: true,
        closeRun: (runId: string) => ({ runId }),
        dismissRun: (runId: string) => ({ runId }),
        expandFab: (runsCount: number) => ({ runsCount }),
    }),
    reducers({
        activeCount: [0, { runsLoaded: (_, { count }) => count }],
        runs: [[] as WizardRunApi[], { runsLoaded: (_, { runs }) => runs }],
        closedRunIds: [[] as string[], { closeRun: (current, { runId }) => [...current, runId] }],
        dismissedRunIds: [
            [] as string[],
            { persist: true },
            { dismissRun: (current, { runId }) => (current.includes(runId) ? current : [...current, runId]) },
        ],
        selectedRunId: [
            null as string | null,
            {
                runsLoaded: (current, { runs }) => (current && runs.some((run) => run.id === current) ? current : null),
                selectRun: (_, { run }) => run.id,
                closeRun: (current, { runId }) => (current === runId ? null : current),
                dismissRun: (current, { runId }) => (current === runId ? null : current),
            },
        ],
        run: [
            null as WizardRunApi | null,
            {
                runsLoaded: (current, { runs }) =>
                    current ? (runs.find((run) => run.id === current.id) ?? current) : null,
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
    selectors({
        visibleRuns: [
            (s) => [s.runs, s.closedRunIds, s.dismissedRunIds],
            (runs: WizardRunApi[], closedRunIds: string[], dismissedRunIds: string[]): WizardRunApi[] =>
                runs.filter((run) => !closedRunIds.includes(run.id) && !dismissedRunIds.includes(run.id)),
        ],
    }),
    listeners(({ actions, cache, props: logicProps, values }) => ({
        checkRuns: async () => {
            if (cache.checking) {
                return
            }
            cache.checking = true
            try {
                const [activePage, completedPage] = await Promise.all([
                    wizardRunsList(logicProps.projectId, {
                        status: ['created', 'running'],
                        limit: RUN_LIST_LIMIT,
                    }),
                    wizardRunsList(logicProps.projectId, { status: ['completed'], limit: RUN_LIST_LIMIT }),
                ])
                const activeRuns = activePage.results.filter(
                    (run) => !completedPage.results.some((completedRun) => completedRun.id === run.id)
                )
                actions.runsLoaded(activePage.count - (activePage.results.length - activeRuns.length), [
                    ...activeRuns,
                    ...completedPage.results,
                ])
            } catch {
                return
            } finally {
                cache.checking = false
            }
        },
        runsLoaded: () => {
            const nextRun =
                values.visibleRuns.find((run) => run.id === values.selectedRunId) ??
                values.visibleRuns[0] ??
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
                            actions.checkRuns()
                        }
                    } catch {
                        actions.checkRuns()
                    }
                }
                return () => stream.close()
            }, 'run-stream')
        },
        closeRun: ({ runId }) => {
            posthog.capture('wizard run sync fab closed', {
                event_source: 'wizard_ui',
                wizard_run_id: runId,
                type: 'dismiss',
            })
            cache.disposables.dispose('run-stream')
            cache.connectedRunId = undefined
            actions.runsLoaded(values.activeCount, values.runs)
        },
        dismissRun: ({ runId }) => {
            posthog.capture('wizard run sync fab closed', {
                event_source: 'wizard_ui',
                wizard_run_id: runId,
                type: 'close_forever',
            })
            cache.disposables.dispose('run-stream')
            cache.connectedRunId = undefined
            actions.runsLoaded(values.activeCount, values.runs)
        },
        expandFab: ({ runsCount }) => {
            posthog.capture('wizard run sync fab expanded', {
                event_source: 'wizard_ui',
                runs_count: runsCount,
            })
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
