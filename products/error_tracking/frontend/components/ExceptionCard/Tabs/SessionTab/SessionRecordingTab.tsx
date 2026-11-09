import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconExternal, IconSparkles } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { sessionRecordingInfoLogic } from 'lib/components/ViewRecordingButton/sessionRecordingInfoLogic'
import { recordingDisabledReason } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Button, TabsContent } from 'lib/ui/quill'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { exceptionCardLogic } from '../../exceptionCardLogic'
import { RecordingEmptyState } from '../RecordingEmptyState'
import { SubHeader } from '../SubHeader'
import { sessionTabLogic } from './sessionTabLogic'

export function SessionRecordingTab(): JSX.Element {
    return (
        <TabsContent value="recording" className="min-h-0 min-w-0 flex-1 overflow-y-auto">
            <SessionRecordingContent />
        </TabsContent>
    )
}

export function SessionRecordingContent(): JSX.Element {
    const { recordingStatus } = useValues(errorPropertiesLogic)
    const { recordingProps, recordingTimestamp, isTimestampOutsideRecording, sessionId } = useValues(sessionTabLogic)
    const { getRecordingExists } = useValues(sessionRecordingInfoLogic)
    const { onSetUpVisionScanner } = useValues(exceptionCardLogic)
    const { checkRecordingInfo } = useActions(sessionRecordingInfoLogic)

    useEffect(() => {
        checkRecordingInfo(sessionId)
    }, [sessionId, checkRecordingInfo])

    // The event's own `$has_recording` is not authoritative: it can be missing, or snapshot false
    // before the replay rows land. So the existence lookup decides whether there is anything to
    // play, and until it answers the player stays and shows its own loading state. Only a confirmed
    // miss gets the explanation, with `$recording_status` choosing the wording.
    const noRecordingReason =
        getRecordingExists(sessionId) === false ? recordingDisabledReason(sessionId, recordingStatus, false) : null

    if (noRecordingReason) {
        // A plain-string reason only says "no recording", which the title already says.
        return (
            <RecordingEmptyState
                title="No recording for this exception"
                description={typeof noRecordingReason === 'string' ? undefined : noRecordingReason}
            />
        )
    }

    const replayUrl = urls.replaySingle(
        sessionId,
        recordingTimestamp === null ? undefined : { unixTimestampMillis: recordingTimestamp }
    )

    return (
        <div className="@container/recording-tab flex h-full min-w-0 flex-col overflow-hidden">
            <SubHeader className="shrink-0 justify-end">
                {onSetUpVisionScanner ? (
                    <Button
                        variant="default"
                        size="sm"
                        onClick={onSetUpVisionScanner}
                        data-attr="error-tracking-recording-tab-scan-with-vision"
                    >
                        <IconSparkles className="text-ai" />
                        {/* The full label does not fit beside "Open in session replay" in the narrowest pane. */}
                        <span className="hidden @xl/recording-tab:inline">
                            Have AI watch every new session with this error
                        </span>
                        <span className="@xl/recording-tab:hidden">Watch with AI</span>
                    </Button>
                ) : null}
                <Button variant="default" size="sm" render={<LinkPrimitive to={replayUrl} target="_blank" />}>
                    Open in session replay
                    <IconExternal />
                </Button>
            </SubHeader>
            {isTimestampOutsideRecording && (
                <LemonBanner type="info" className="m-2">
                    The exception occurred outside the recorded session timeframe. It is attached to a session but not
                    visible in the recording.
                </LemonBanner>
            )}
            <div className="flex min-h-0 min-w-0 flex-1 items-center justify-center overflow-hidden">
                <SessionRecordingPlayer
                    {...recordingProps}
                    mode={SessionRecordingPlayerMode.Standard}
                    autoPlay={true}
                    noMeta
                    noBorder
                    withSidebar={false}
                />
            </div>
        </div>
    )
}
