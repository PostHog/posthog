import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import type { logsViewsListLogicType } from './logsViewsListLogicType'
import { LogsViewsLogicProps, logsViewsLogic } from './logsViewsLogic'

export const logsViewsListLogic = kea<logsViewsListLogicType>([
    props({} as LogsViewsLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'logs', 'frontend', 'components', 'LogsViews', 'logsViewsListLogic', key]),

    connect((props: LogsViewsLogicProps) => ({
        values: [logsViewerFiltersLogic({ id: props.id }), ['filters']],
        actions: [logsViewsLogic({ id: props.id }), ['createView', 'createViewSuccess', 'loadView', 'loadViews']],
    })),

    actions({
        openModal: true,
        closeModal: true,
        openSaveModal: true,
        closeSaveModal: true,
        setViewName: (viewName: string) => ({ viewName }),
        saveView: true,
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
                loadView: () => false,
            },
        ],
        isSaveModalOpen: [
            false,
            {
                openSaveModal: () => true,
                closeSaveModal: () => false,
                createViewSuccess: () => false,
            },
        ],
        viewName: [
            '',
            {
                setViewName: (_, { viewName }) => viewName,
                closeSaveModal: () => '',
                createViewSuccess: () => '',
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        openModal: () => {
            actions.loadViews()
        },
        saveView: () => {
            const name = values.viewName.trim()
            if (!name) {
                return
            }
            actions.createView({ name, filters: { ...values.filters } })
        },
    })),
])
