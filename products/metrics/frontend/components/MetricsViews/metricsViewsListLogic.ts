import { actions, connect, kea, listeners, path, reducers } from 'kea'

import { metricsViewerLogic } from '../metricsViewerLogic'
import type { metricsViewsListLogicType } from './metricsViewsListLogicType'
import { metricsViewsLogic } from './metricsViewsLogic'

export const metricsViewsListLogic = kea<metricsViewsListLogicType>([
    path(['products', 'metrics', 'frontend', 'components', 'MetricsViews', 'metricsViewsListLogic']),

    connect(() => ({
        values: [metricsViewerLogic, ['savedFilters'], metricsViewsLogic, ['viewsLoading']],
        actions: [metricsViewsLogic, ['createView', 'createViewSuccess', 'loadView', 'loadViews']],
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
            // Guard against double-submit (Enter + click, or a rapid double-click): a create is
            // already in flight while `viewsLoading` is set, and each success prepends a duplicate.
            if (!name || values.viewsLoading) {
                return
            }
            actions.createView({ name, filters: values.savedFilters })
        },
    })),
])
