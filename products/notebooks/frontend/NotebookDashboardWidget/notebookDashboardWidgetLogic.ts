import { MakeLogicType, actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiError } from 'lib/api-error'
import { teamLogic } from 'scenes/teamLogic'

import {
    notebooksRunsCreate,
    notebooksRunsInterruptCreate,
    notebooksRunsRetrieve,
    notebooksWidgetSnapshotPublish,
    notebooksWidgetSnapshotRetrieve,
    notebooksWidgetSource,
} from '../generated/api'
import type { WidgetSnapshotApi } from '../generated/api.schemas'

export interface NotebookDashboardWidgetProps {
    tileId: number
    notebookShortId: string
    snapshotId: string
    onSnapshotPublished?: () => void
}

export interface notebookDashboardWidgetValues {
    snapshot: WidgetSnapshotApi | null
    snapshotLoading: boolean
    source: string | null
    sourceLoading: boolean
    sourceOpen: boolean
    refreshing: boolean
    polling: boolean
    stopping: boolean
    runId: string | null
    error: string | null
    progress: string | null
}
export interface notebookDashboardWidgetActions {
    loadSnapshot: () => void
    loadSnapshotSuccess: (snapshot: WidgetSnapshotApi | null) => { snapshot: WidgetSnapshotApi | null }
    loadSnapshotFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadSource: () => void
    loadSourceFailure: (error: string) => { error: string }
    setSourceOpen: (sourceOpen: boolean) => { sourceOpen: boolean }
    refresh: () => void
    pollRun: () => void
    stopRun: () => void
    setRefreshing: (refreshing: boolean) => { refreshing: boolean }
    setPolling: (polling: boolean) => { polling: boolean }
    setStopping: (stopping: boolean) => { stopping: boolean }
    setRunId: (runId: string | null) => { runId: string | null }
    setError: (error: string | null) => { error: string | null }
    setProgress: (progress: string | null) => { progress: string | null }
}
export type notebookDashboardWidgetLogicType = MakeLogicType<
    notebookDashboardWidgetValues,
    notebookDashboardWidgetActions,
    NotebookDashboardWidgetProps
>

export const notebookDashboardWidgetLogic = kea<notebookDashboardWidgetLogicType>([
    props({} as NotebookDashboardWidgetProps),
    key(({ tileId, snapshotId }) => `${tileId}-${snapshotId}`),
    path((key) => ['products', 'notebooks', 'notebookDashboardWidgetLogic', key]),
    actions({
        refresh: () => ({}),
        pollRun: () => ({}),
        stopRun: () => ({}),
        setSourceOpen: (sourceOpen: boolean) => ({ sourceOpen }),
        setRefreshing: (refreshing: boolean) => ({ refreshing }),
        setPolling: (polling: boolean) => ({ polling }),
        setStopping: (stopping: boolean) => ({ stopping }),
        setRunId: (runId: string | null) => ({ runId }),
        setError: (error: string | null) => ({ error }),
        setProgress: (progress: string | null) => ({ progress }),
    }),
    loaders(({ props, values }) => ({
        snapshot: [
            null as WidgetSnapshotApi | null,
            {
                loadSnapshot: () =>
                    notebooksWidgetSnapshotRetrieve(
                        String(teamLogic.values.currentTeamId),
                        props.notebookShortId,
                        values.snapshot?.id ?? props.snapshotId
                    ),
            },
        ],
        source: [
            null as string | null,
            {
                loadSource: async () => {
                    if (!values.snapshot) {
                        return null
                    }
                    return (
                        await notebooksWidgetSource(
                            String(teamLogic.values.currentTeamId),
                            props.notebookShortId,
                            values.snapshot.node_id,
                            { version_id: values.snapshot.version_id }
                        )
                    ).source
                },
            },
        ],
    })),
    reducers({
        sourceOpen: [false, { setSourceOpen: (_, { sourceOpen }) => sourceOpen }],
        refreshing: [false, { setRefreshing: (_, { refreshing }) => refreshing }],
        polling: [false, { setPolling: (_, { polling }) => polling }],
        stopping: [false, { setStopping: (_, { stopping }) => stopping }],
        runId: [null as string | null, { setRunId: (_, { runId }) => runId }],
        error: [null as string | null, { setError: (_, { error }) => error, loadSnapshot: () => null }],
        progress: [null as string | null, { setProgress: (_, { progress }) => progress }],
    }),
    listeners(({ actions, values, props, cache }) => ({
        loadSnapshotFailure: ({ errorObject }) =>
            actions.setError(
                (errorObject instanceof ApiError && errorObject.detail) ||
                    'Could not load the saved results. Check your notebook access and try again.'
            ),
        loadSourceFailure: () => actions.setError('Could not load the widget source. Open the notebook to try again.'),
        setSourceOpen: ({ sourceOpen }) => {
            if (sourceOpen) {
                actions.loadSource()
            }
        },
        refresh: async () => {
            if (values.refreshing || !values.snapshot || !props.onSnapshotPublished) {
                return
            }
            const signal: AbortSignal = cache.abortSignal
            actions.setRefreshing(true)
            actions.setError(null)
            actions.setProgress('Starting notebook…')
            try {
                const run = await notebooksRunsCreate(String(teamLogic.values.currentTeamId), props.notebookShortId, {
                    include_prepared_insights: true,
                })
                if (signal.aborted) {
                    return
                }
                actions.setRunId(run.run_id)
                actions.pollRun()
                cache.disposables.add(
                    () => {
                        const timer = setInterval(() => actions.pollRun(), 2000)
                        return () => clearInterval(timer)
                    },
                    'notebook-run',
                    { pauseOnPageHidden: false }
                )
            } catch (error) {
                if (signal.aborted) {
                    return
                }
                actions.setError(error instanceof Error ? error.message : 'Could not start the notebook. Try again.')
                actions.setRefreshing(false)
                actions.setProgress(null)
            }
        },
        pollRun: async () => {
            if (values.polling || !values.runId || !values.snapshot) {
                return
            }
            const signal: AbortSignal = cache.abortSignal
            actions.setPolling(true)
            try {
                const projectId = String(teamLogic.values.currentTeamId)
                const run = await notebooksRunsRetrieve(projectId, props.notebookShortId, values.runId)
                if (signal.aborted) {
                    return
                }
                if (run.status === 'running') {
                    actions.setError(null)
                    actions.setProgress(`Running cell ${run.current_index + 1} of ${run.cell_count}…`)
                    cache.disposables.add(
                        () => {
                            const timer = setInterval(() => actions.pollRun(), 2000)
                            return () => clearInterval(timer)
                        },
                        'notebook-run',
                        { pauseOnPageHidden: false }
                    )
                    return
                }
                cache.disposables.dispose('notebook-run')
                actions.setRunId(null)
                if (run.status !== 'done') {
                    throw new Error(run.error || 'The notebook did not finish. Your saved results have not changed.')
                }
                actions.setProgress('Saving results…')
                const snapshot = await notebooksWidgetSnapshotPublish(projectId, props.notebookShortId, {
                    node_id: values.snapshot.node_id,
                    version_id: values.snapshot.version_id,
                    notebook_run_id: run.run_id,
                    previous_snapshot_id: values.snapshot.id,
                    tile_id: props.tileId,
                })
                if (signal.aborted) {
                    return
                }
                actions.loadSnapshotSuccess(snapshot)
                props.onSnapshotPublished?.()
            } catch (error) {
                if (signal.aborted) {
                    return
                }
                actions.setError(
                    error instanceof Error
                        ? error.message
                        : 'Could not refresh this widget. Your saved results have not changed.'
                )
                cache.disposables.dispose('notebook-run')
            } finally {
                actions.setPolling(false)
                if (!values.runId) {
                    actions.setRefreshing(false)
                    actions.setProgress(null)
                }
            }
        },
        stopRun: async () => {
            if (!values.runId || values.stopping) {
                return
            }
            const signal: AbortSignal = cache.abortSignal
            actions.setStopping(true)
            try {
                await notebooksRunsInterruptCreate(
                    String(teamLogic.values.currentTeamId),
                    props.notebookShortId,
                    values.runId
                )
                if (signal.aborted) {
                    return
                }
                actions.pollRun()
            } catch {
                if (signal.aborted) {
                    return
                }
                actions.setError('Could not stop the notebook. Open it to check the run.')
            } finally {
                actions.setStopping(false)
            }
        },
    })),
    afterMount(({ actions, cache }) => {
        cache.disposables.add(
            () => {
                const controller = new AbortController()
                cache.abortSignal = controller.signal
                return () => controller.abort()
            },
            'lifecycle',
            { pauseOnPageHidden: false }
        )
        actions.loadSnapshot()
    }),
])
