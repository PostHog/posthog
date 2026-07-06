import { actions, connect, kea, listeners, path, reducers } from 'kea'

import { tracingFiltersLogic } from '../tracingFiltersLogic'
import type { tracingViewsListLogicType } from './tracingViewsListLogicType'
import { tracingViewsLogic } from './tracingViewsLogic'

export const tracingViewsListLogic = kea<tracingViewsListLogicType>([
    path(['products', 'tracing', 'frontend', 'savedViews', 'tracingViewsListLogic']),

    connect(() => ({
        values: [tracingFiltersLogic, ['filters']],
        actions: [tracingViewsLogic, ['createView', 'createViewSuccess', 'loadView', 'loadViews']],
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
            // Persist only the subset a view should restore — drop ephemeral compare-mode state.
            const { dateRange, serviceNames, filterGroup, orderBy, orderDirection, viewMode } = values.filters
            actions.createView({
                name,
                filters: { dateRange, serviceNames, filterGroup, orderBy, orderDirection, viewMode },
            })
        },
    })),
])
