import { MakeLogicType, actions, defaults, kea, listeners, path, props, reducers } from 'kea'

import {
    buildWidgetTileMetadataPatch,
    getWidgetEditModalTileDefaults,
    widgetEditModalTileActions,
} from 'products/dashboards/frontend/widgets/editWidgetModalBuilders'
import type { DashboardWidgetEditModalProps } from 'products/dashboards/frontend/widgets/registry'

export interface editNotebookWidgetValues {
    tileName: string
    tileDescription: string
    saving: boolean
    error: string | null
}
export interface editNotebookWidgetActions {
    setTileName: (tileName: string) => { tileName: string }
    setTileDescription: (tileDescription: string) => { tileDescription: string }
    submit: () => void
    setSaving: (saving: boolean) => { saving: boolean }
    setError: (error: string | null) => { error: string | null }
}
export type editNotebookWidgetLogicType = MakeLogicType<
    editNotebookWidgetValues,
    editNotebookWidgetActions,
    DashboardWidgetEditModalProps
>

export const editNotebookWidgetLogic = kea<editNotebookWidgetLogicType>([
    props({} as DashboardWidgetEditModalProps),
    path(['products', 'notebooks', 'editNotebookWidgetLogic']),
    actions({
        ...widgetEditModalTileActions,
        submit: () => ({}),
        setSaving: (saving: boolean) => ({ saving }),
        setError: (error: string | null) => ({ error }),
    }),
    defaults(({ props }) => getWidgetEditModalTileDefaults(props)),
    reducers({
        tileName: ['', { setTileName: (_, { tileName }) => tileName }],
        tileDescription: ['', { setTileDescription: (_, { tileDescription }) => tileDescription }],
        saving: [false, { setSaving: (_, { saving }) => saving }],
        error: [null as string | null, { setError: (_, { error }) => error }],
    }),
    listeners(({ actions, values, props }) => ({
        submit: async () => {
            if (values.saving) {
                return
            }
            actions.setSaving(true)
            actions.setError(null)
            try {
                await props.onSave(
                    props.config,
                    buildWidgetTileMetadataPatch(props, values.tileName, values.tileDescription)
                )
                props.onClose()
            } catch {
                actions.setError('Could not save the widget settings. Try again.')
            } finally {
                actions.setSaving(false)
            }
        },
    })),
])
