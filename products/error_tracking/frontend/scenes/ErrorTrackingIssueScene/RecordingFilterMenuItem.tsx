import { useActions, useValues } from 'kea'

import { IconRewindPlay } from '@posthog/icons'

import { DropdownMenuCheckboxItem, DropdownMenuGroup, DropdownMenuLabel } from 'lib/ui/quill'

import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { issueRecordingFilterLogic } from './issueRecordingFilterLogic'
import { RECORDING_FILTER_LABEL } from './recordingFilterLabel'

export function RecordingFilterMenuItem(): JSX.Element {
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const { onlyWithRecording } = useValues(issueRecordingFilterLogic({ issueId }))
    const { setOnlyWithRecording } = useActions(issueRecordingFilterLogic({ issueId }))

    return (
        <DropdownMenuGroup>
            <DropdownMenuLabel>Session replay</DropdownMenuLabel>
            <DropdownMenuCheckboxItem
                checked={onlyWithRecording}
                closeOnClick
                onCheckedChange={(checked) => setOnlyWithRecording(checked)}
                data-attr="error-tracking-issue-filter-with-recording"
            >
                <IconRewindPlay />
                {RECORDING_FILTER_LABEL}
            </DropdownMenuCheckboxItem>
        </DropdownMenuGroup>
    )
}
