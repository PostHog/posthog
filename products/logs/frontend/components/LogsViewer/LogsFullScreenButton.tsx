import { useActions } from 'kea'

import { IconExpand45 } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { logsViewerModalLogic } from './LogsViewerModal/logsViewerModalLogic'

/**
 * Maximises the whole viewer surface. Viewer-scoped (not scene-scoped: it only applies to the
 * Logs Viewer tab), so it lives at the top-right of the query bar rather than in the results bar.
 */
export const LogsFullScreenButton = ({ id }: { id: string }): JSX.Element => {
    const { openLogsViewerModal } = useActions(logsViewerModalLogic)

    return (
        <LemonButton
            size="small"
            type="secondary"
            icon={<IconExpand45 />}
            onClick={() => openLogsViewerModal({ id })}
            tooltip="Full screen"
        />
    )
}
