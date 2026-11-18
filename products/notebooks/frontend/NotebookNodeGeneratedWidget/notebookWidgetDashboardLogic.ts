import { LogicWrapper, MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { dashboardsModel } from '~/models/dashboardsModel'

import { notebooksWidgetSnapshotPublish } from '../generated/api'

export interface NotebookWidgetDashboardProps {
    notebookShortId: string
    nodeId: string
    versionId: string
    title: string
    persistNotebook: () => Promise<void>
}

export interface notebookWidgetDashboardValues {
    isOpen: boolean
    saving: boolean
    error: string | null
    dashboardId: number | null
}
export interface notebookWidgetDashboardActions {
    loadDashboards: () => void
    open: () => void
    close: () => void
    selectDashboard: (dashboardId: number | null) => { dashboardId: number | null }
    addToDashboard: () => void
    setSaving: (saving: boolean) => { saving: boolean }
    setError: (error: string | null) => { error: string | null }
}
export type notebookWidgetDashboardLogicType = MakeLogicType<
    notebookWidgetDashboardValues,
    notebookWidgetDashboardActions,
    NotebookWidgetDashboardProps
>

export const notebookWidgetDashboardLogic: LogicWrapper<notebookWidgetDashboardLogicType> =
    kea<notebookWidgetDashboardLogicType>([
        props({} as NotebookWidgetDashboardProps),
        key(({ notebookShortId, nodeId }) => `${notebookShortId}-${nodeId}`),
        path((key) => ['products', 'notebooks', 'notebookWidgetDashboardLogic', key]),
        connect({ actions: [dashboardsModel, ['loadDashboards']] }),
        actions({
            open: () => ({}),
            close: () => ({}),
            addToDashboard: () => ({}),
            selectDashboard: (dashboardId: number | null) => ({ dashboardId }),
            setSaving: (saving: boolean) => ({ saving }),
            setError: (error: string | null) => ({ error }),
        }),
        reducers({
            isOpen: [false, { open: () => true, close: () => false }],
            saving: [false, { setSaving: (_, { saving }) => saving }],
            error: [null as string | null, { setError: (_, { error }) => error, open: () => null }],
            dashboardId: [null as number | null, { selectDashboard: (_, { dashboardId }) => dashboardId }],
        }),
        listeners(({ actions, values, props }) => ({
            open: () => actions.loadDashboards(),
            addToDashboard: async () => {
                if (values.saving || !values.dashboardId) {
                    return
                }
                const dashboardId = values.dashboardId
                actions.setSaving(true)
                actions.setError(null)
                try {
                    await props.persistNotebook()
                    const projectId = String(teamLogic.values.currentTeamId)
                    await notebooksWidgetSnapshotPublish(projectId, props.notebookShortId, {
                        node_id: props.nodeId,
                        version_id: props.versionId,
                        dashboard_id: dashboardId,
                        name: props.title,
                    })
                    lemonToast.success('Widget added to dashboard')
                    actions.close()
                } catch (error) {
                    actions.setError(error instanceof Error ? error.message : 'Could not add this widget. Try again.')
                } finally {
                    actions.setSaving(false)
                }
            },
        })),
    ])
