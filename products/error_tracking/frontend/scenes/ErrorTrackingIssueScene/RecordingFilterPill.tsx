import { useActions, useValues } from 'kea'

import { IconRewindPlay, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import 'lib/components/UniversalFilters/UniversalFilterButton.scss'

import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { issueRecordingFilterLogic } from './issueRecordingFilterLogic'
import { RECORDING_FILTER_LABEL } from './recordingFilterLabel'

// Uses the property filter pill's markup and styles, so it sits in the same row as those pills and looks like one.
export function RecordingFilterPill(): JSX.Element {
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const { setOnlyWithRecording } = useActions(issueRecordingFilterLogic({ issueId }))

    return (
        <div
            className="UniversalFilterButton UniversalFilterButton--closeable inline-flex items-center"
            data-attr="error-tracking-issue-filter-pill-recording"
        >
            <div className="flex flex-1 items-center gap-1 truncate">
                <IconRewindPlay />
                <span className="UniversalFilterButton-content flex flex-1 items-center truncate">
                    {RECORDING_FILTER_LABEL}
                </span>
            </div>
            <LemonButton
                size="xsmall"
                icon={<IconX className="h-3 w-3" />}
                onClick={() => setOnlyWithRecording(false)}
                aria-label={`Remove filter: ${RECORDING_FILTER_LABEL}`}
                className="p-0.5"
            />
        </div>
    )
}
