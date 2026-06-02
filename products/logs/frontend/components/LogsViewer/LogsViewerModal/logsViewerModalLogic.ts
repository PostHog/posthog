import { actions, kea, path, reducers } from 'kea'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'

import type { logsViewerModalLogicType } from './logsViewerModalLogicType'

export interface OpenLogsViewerModalOptions {
    id?: string
    fullScreen?: boolean
    initialFilters?: Partial<LogsViewerFilters>
    // Show an "Open in Logs" link that deep-links to the full Logs scene with the modal's filters.
    // Off by default — callers already on the Logs scene don't need it; cross-product openers do.
    showOpenInScene?: boolean
}

export const logsViewerModalLogic = kea<logsViewerModalLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'LogsViewerModal', 'logsViewerModalLogic']),
    actions({
        openLogsViewerModal: (options?: OpenLogsViewerModalOptions) => ({
            id: options?.id ?? 'modal',
            fullScreen: options?.fullScreen ?? true,
            initialFilters: options?.initialFilters ?? null,
            showOpenInScene: options?.showOpenInScene ?? false,
        }),
        closeLogsViewerModal: true,
    }),
    reducers({
        isOpen: [
            false,
            {
                openLogsViewerModal: () => true,
                closeLogsViewerModal: () => false,
            },
        ],
        viewerId: [
            'modal' as string,
            {
                openLogsViewerModal: (_, { id }) => id,
            },
        ],
        fullScreen: [
            true,
            {
                openLogsViewerModal: (_, { fullScreen }) => fullScreen,
            },
        ],
        initialFilters: [
            null as Partial<LogsViewerFilters> | null,
            {
                openLogsViewerModal: (_, { initialFilters }) => initialFilters,
                closeLogsViewerModal: () => null,
            },
        ],
        showOpenInScene: [
            false,
            {
                openLogsViewerModal: (_, { showOpenInScene }) => showOpenInScene,
                closeLogsViewerModal: () => false,
            },
        ],
    }),
])
