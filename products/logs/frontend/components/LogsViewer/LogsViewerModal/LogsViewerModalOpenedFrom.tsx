import { useActions, useValues } from 'kea'

import { IconRewindPlay, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LogsViewerModalOrigin, logsViewerModalLogic } from './logsViewerModalLogic'

const ORIGIN_COPY: Record<LogsViewerModalOrigin, { icon: JSX.Element; label: string; back: string }> = {
    recording: { icon: <IconRewindPlay />, label: 'Opened from recording', back: 'Back to recording' },
    exception: { icon: <IconWarning />, label: 'Opened from exception', back: 'Back to exception' },
}

export function LogsViewerModalOpenedFrom(): JSX.Element | null {
    const { openedFrom, sessionId } = useValues(logsViewerModalLogic)
    const { closeLogsViewerModal } = useActions(logsViewerModalLogic)

    if (!openedFrom) {
        return null
    }

    const copy = ORIGIN_COPY[openedFrom]

    return (
        <div
            className="flex flex-1 min-w-0 flex-wrap items-center gap-2 rounded border border-accent bg-accent-highlight-secondary px-2 py-1 text-xs"
            data-attr="logs-modal-opened-from"
        >
            <span className="flex items-center gap-1.5 font-semibold">
                {copy.icon}
                {copy.label}
            </span>
            {sessionId && (
                <span className="flex items-center gap-1 text-muted min-w-0">
                    <span className="shrink-0">Showing logs from session</span>
                    <span className="font-mono truncate" translate="no" title={sessionId}>
                        {sessionId}
                    </span>
                </span>
            )}
            <LemonButton
                size="xsmall"
                type="secondary"
                className="ml-auto"
                onClick={closeLogsViewerModal}
                data-attr="logs-modal-back-to-origin"
            >
                {copy.back}
            </LemonButton>
        </div>
    )
}
