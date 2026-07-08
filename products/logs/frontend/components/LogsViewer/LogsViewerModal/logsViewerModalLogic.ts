import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'

import { LogsViewerFilters } from 'products/logs/frontend/components/LogsViewer/config/types'

import type { logsViewerModalLogicType } from './logsViewerModalLogicType'

export interface OpenLogsViewerModalOptions {
    id?: string
    fullScreen?: boolean
    initialFilters?: Partial<LogsViewerFilters>
}

export const logsViewerModalLogic = kea<logsViewerModalLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'LogsViewerModal', 'logsViewerModalLogic']),
    connect(() => ({
        actions: [router, ['locationChanged']],
    })),
    actions({
        openLogsViewerModal: (options?: OpenLogsViewerModalOptions) => ({
            id: options?.id ?? 'modal',
            fullScreen: options?.fullScreen ?? true,
            initialFilters: options?.initialFilters ?? null,
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
    }),
    listeners(({ values, actions, cache }) => ({
        locationChanged: ({ pathname }) => {
            // close the (often full-screen) modal when navigating to a new scene, e.g. via cmd+k.
            // query/hash-only changes fire locationChanged too (the viewer syncs filters to the
            // URL), so only react to an actual pathname change.
            if (pathname === cache.lastPathname) {
                return
            }
            cache.lastPathname = pathname
            if (values.isOpen) {
                actions.closeLogsViewerModal()
            }
        },
    })),
    afterMount(({ cache }) => {
        cache.lastPathname = router.values.location.pathname
    }),
])
