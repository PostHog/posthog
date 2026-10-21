import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import { recordingScanBlock } from '../utils/scanEligibility'
import { SummarizeButton } from './SummarizeButton'
import { SummarizeExplainer } from './SummarizeExplainer'
import { useSummarizeBlockedReason } from './useSummarizeBlockedReason'

export function SummarizeRecordingBar({
    extraActions,
}: {
    /** Recording actions the host places beside the summarize button. */
    extraActions?: React.ReactNode
}): JSX.Element | null {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { isNotFound, isRecordingDeleted } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))

    if (!sessionRecordingId || isNotFound || isRecordingDeleted) {
        return null
    }
    return <SummarizeRecordingBarContent sessionId={sessionRecordingId} extraActions={extraActions} />
}

function SummarizeRecordingBarContent({
    sessionId,
    extraActions,
}: {
    sessionId: string
    extraActions?: React.ReactNode
}): JSX.Element {
    const { defaultSummarizer } = useValues(observationsDockLogic({ sessionId }))
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const scanBlock = recordingScanBlock(sessionPlayerMetaData)
    const summarizeBlockedReason = useSummarizeBlockedReason(scanBlock)(defaultSummarizer)

    return (
        <div
            className="flex items-center gap-2 lg:gap-3 h-11 px-3 shrink-0 border-t bg-surface-primary"
            // Frozen: dashboards and selectors still find the bar under its old name.
            data-attr="vision-observations-dock"
        >
            <SummarizeButton sessionId={sessionId} scanBlock={scanBlock} />
            <SummarizeExplainer />
            {extraActions}
            {summarizeBlockedReason && (
                <Tooltip title={summarizeBlockedReason}>
                    <span className="ml-auto text-muted text-xs truncate" data-attr="vision-dock-skipped">
                        {scanBlock ? `Skipped: ${scanBlock.label.toLowerCase()}` : summarizeBlockedReason}
                    </span>
                </Tooltip>
            )}
        </div>
    )
}
