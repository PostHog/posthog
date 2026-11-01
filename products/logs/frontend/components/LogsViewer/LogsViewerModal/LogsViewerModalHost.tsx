import { useValues } from 'kea'
import { Suspense } from 'react'

import { useKeepMountedWhileOpen } from 'lib/hooks/useKeepMountedWhileOpen'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { logsViewerModalLogic } from './logsViewerModalLogic'

// The viewer's sparkline anchors chart.js, so the modal loads only when it opens.
const LogsViewerModal = lazyWithRetry(() => import('./LogsViewerModal').then((m) => ({ default: m.LogsViewerModal })))

export function LogsViewerModalHost(): JSX.Element | null {
    const { isOpen } = useValues(logsViewerModalLogic)
    const shouldRender = useKeepMountedWhileOpen(isOpen)
    return shouldRender ? (
        <Suspense fallback={null}>
            <LogsViewerModal />
        </Suspense>
    ) : null
}
