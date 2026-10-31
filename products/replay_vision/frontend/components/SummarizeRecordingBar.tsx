import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { playerUsesWatchLayout } from 'scenes/session-recordings/playlist/replayLayout'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import { recordingScanBlock } from '../utils/scanEligibility'
import { SummarizeButton } from './SummarizeButton'
import { SummarizeExplainer } from './SummarizeExplainer'
import { useSummarizeBlockedReason } from './useSummarizeBlockedReason'

export function SummarizeRecordingBar({
    extraActions,
    inline = false,
}: {
    /** Recording actions the host places beside the summarize button. */
    extraActions?: React.ReactNode
    /** Just the controls, for a host that places them inside its own row. */
    inline?: boolean
}): JSX.Element | null {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { isNotFound, isRecordingDeleted } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))

    if (!sessionRecordingId || isNotFound || isRecordingDeleted) {
        return null
    }
    return <SummarizeRecordingBarContent sessionId={sessionRecordingId} extraActions={extraActions} inline={inline} />
}

function SummarizeRecordingBarContent({
    sessionId,
    extraActions,
    inline,
}: {
    sessionId: string
    extraActions?: React.ReactNode
    inline: boolean
}): JSX.Element {
    const { defaultSummarizer } = useValues(observationsDockLogic({ sessionId }))
    const { sessionPlayerMetaData, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { replayLayout } = useValues(playerSettingsLogic)
    const scanBlock = recordingScanBlock(sessionPlayerMetaData)
    const summarizeBlockedReason = useSummarizeBlockedReason(scanBlock)(defaultSummarizer)

    return (
        <div
            className={
                inline
                    ? 'flex items-center gap-2 min-w-0'
                    : 'flex items-center gap-2 lg:gap-3 h-11 px-3 shrink-0 border-t bg-surface-primary'
            }
            // Frozen: dashboards and selectors still find the bar under its old name.
            data-attr="vision-observations-dock"
        >
            <SummarizeButton
                sessionId={sessionId}
                scanBlock={scanBlock}
                inWatchLayout={playerUsesWatchLayout(replayLayout, logicProps)}
            />
            <SummarizeExplainer />
            {extraActions}
            {/* The inline row has no room for it, and the disabled button already says why on hover. */}
            {!inline && summarizeBlockedReason && (
                <Tooltip title={summarizeBlockedReason}>
                    <span className="ml-auto text-muted text-xs truncate" data-attr="vision-dock-skipped">
                        {scanBlock ? `Skipped: ${scanBlock.label.toLowerCase()}` : summarizeBlockedReason}
                    </span>
                </Tooltip>
            )}
        </div>
    )
}
