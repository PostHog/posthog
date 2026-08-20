import { useActions } from 'kea'

import { IconExpand45 } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LogsViewerScope } from './config/types'
import { logsViewerModalLogic } from './LogsViewerModal/logsViewerModalLogic'

/**
 * Maximises the whole viewer surface. Viewer-scoped (not scene-scoped: it only applies to the
 * Logs Viewer tab), so it lives at the top-right of the query bar rather than in the results bar.
 *
 * `scope` carries the embedding scene's scope (a person, a pinned trace filter) into the modal,
 * which mounts its own viewer under the same id.
 */
export const LogsFullScreenButton = ({ id, scope }: { id: string; scope?: LogsViewerScope }): JSX.Element => {
    const { openLogsViewerModal } = useActions(logsViewerModalLogic)

    return (
        <LemonButton
            size="small"
            type="secondary"
            icon={<IconExpand45 />}
            onClick={() => openLogsViewerModal({ id, ...scope })}
            tooltip="Full screen"
        />
    )
}
