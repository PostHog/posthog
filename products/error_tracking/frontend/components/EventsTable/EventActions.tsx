import { router } from 'kea-router'

import { IconAI, IconEllipsis, IconLive } from '@posthog/icons'

import { ErrorEventType } from 'lib/components/Errors/types'
import { getRecordingStatus, getSessionId } from 'lib/components/Errors/utils'
import { useRecordingButton } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { IconLink, IconPlayCircle } from 'lib/lemon-ui/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from 'lib/ui/quill'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { useViewLogsButton } from 'products/logs/frontend/components/ViewLogsButton'

import { cancelEvent } from '../../utils'

export function EventActions({ record }: { record: ErrorEventType }): JSX.Element {
    const sessionId = getSessionId(record.properties)
    const recordingStatus = getRecordingStatus(record.properties)
    const hasRecording = record.properties.$has_recording as boolean | undefined
    const {
        onClick: viewRecording,
        disabledReason: recordingDisabledReason,
        warningReason: recordingWarningReason,
    } = useRecordingButton({
        sessionId: sessionId ?? '',
        recordingStatus,
        hasRecording,
        timestamp: record.timestamp,
    })
    const logs = useViewLogsButton({ sessionId, timestamp: record.timestamp })
    const recordingTooltip =
        typeof recordingDisabledReason === 'string' ? recordingDisabledReason : recordingWarningReason

    return (
        <div onClick={(event) => cancelEvent(event)}>
            <DropdownMenu>
                <DropdownMenuTrigger render={<Button variant="default" size="icon-sm" aria-label="More actions" />}>
                    <IconEllipsis />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-auto min-w-44">
                    <DropdownMenuItem
                        disabled={Boolean(recordingDisabledReason)}
                        onClick={viewRecording}
                        title={recordingTooltip}
                        data-attr="error-tracking-view-recording"
                    >
                        <IconPlayCircle />
                        View recording
                    </DropdownMenuItem>
                    {logs.enabled && (
                        <DropdownMenuItem
                            disabled={!logs.onClick}
                            onClick={logs.onClick}
                            title={logs.disabledReason}
                            data-attr="error-tracking-view-logs"
                        >
                            <IconLive />
                            View logs
                        </DropdownMenuItem>
                    )}
                    {record.properties.$ai_trace_id && (
                        <DropdownMenuItem
                            onClick={() =>
                                router.actions.push(
                                    urls.aiObservabilityTrace(record.properties.$ai_trace_id, {
                                        event: record.uuid,
                                        timestamp: record.timestamp,
                                    })
                                )
                            }
                        >
                            <IconAI />
                            View LLM trace
                        </DropdownMenuItem>
                    )}
                    <DropdownMenuItem
                        data-attr="events-table-event-link"
                        onClick={() => {
                            void copyToClipboard(
                                urls.absolute(urls.currentProject(urls.event(String(record.uuid), record.timestamp))),
                                'link to event'
                            )
                        }}
                    >
                        <IconLink />
                        Copy event link
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
