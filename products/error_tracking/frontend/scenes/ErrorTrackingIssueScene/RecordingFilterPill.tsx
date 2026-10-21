import { useActions, useValues } from 'kea'

import { Chip, ChipClose } from 'lib/ui/quill'

import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { issueRecordingFilterLogic } from './issueRecordingFilterLogic'
import { RECORDING_FILTER_LABEL } from './recordingFilterLabel'

export function RecordingFilterPill(): JSX.Element {
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const { setOnlyWithRecording } = useActions(issueRecordingFilterLogic({ issueId }))

    return (
        <Chip data-attr="error-tracking-issue-filter-pill-recording">
            {RECORDING_FILTER_LABEL}
            <ChipClose
                aria-label={`Remove filter: ${RECORDING_FILTER_LABEL}`}
                onClick={() => setOnlyWithRecording(false)}
            />
        </Chip>
    )
}
