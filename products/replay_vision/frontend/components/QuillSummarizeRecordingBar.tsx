import { useValues } from 'kea'

import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { recordingScanBlock } from '../utils/scanEligibility'
import { QuillSummarizeButton } from './QuillSummarizeButton'

/** The summarize controls for the watch layouts, placed inside the title block's action row. */
export function QuillSummarizeRecordingBar(): JSX.Element | null {
    const { sessionRecordingId, logicProps, sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const { isNotFound, isRecordingDeleted } = useValues(sessionRecordingDataCoordinatorLogic(logicProps))

    if (!sessionRecordingId || isNotFound || isRecordingDeleted) {
        return null
    }
    return (
        // Frozen: dashboards and selectors still find the bar under its old name.
        <div className="flex items-center gap-2 min-w-0" data-attr="vision-observations-dock">
            <QuillSummarizeButton
                sessionId={sessionRecordingId}
                scanBlock={recordingScanBlock(sessionPlayerMetaData)}
            />
        </div>
    )
}
