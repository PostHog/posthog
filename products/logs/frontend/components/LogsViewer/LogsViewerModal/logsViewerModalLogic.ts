import { actions, kea, path, reducers } from 'kea'

import type { logsViewerModalLogicType } from './logsViewerModalLogicType'

export const logsViewerModalLogic = kea<logsViewerModalLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsViewer', 'LogsViewerModal', 'logsViewerModalLogic']),
    actions({
        openLogsViewerModal: (options?: { id?: string; fullScreen?: boolean }) => ({
            id: options?.id ?? 'modal',
            fullScreen: options?.fullScreen ?? true,
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
    }),
])
