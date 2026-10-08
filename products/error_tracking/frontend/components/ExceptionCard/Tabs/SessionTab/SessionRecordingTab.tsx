import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { sessionRecordingInfoLogic } from 'lib/components/ViewRecordingButton/sessionRecordingInfoLogic'
import { recordingDisabledReason } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Button, TabsContent } from 'lib/ui/quill'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

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
        return (
            <div className="flex h-full w-full items-center justify-center p-4">
                <p className="max-w-md text-center text-secondary">{noRecordingReason}</p>
            </div>
        )
    }

    const replayUrl = urls.replaySingle(
        sessionId,
        recordingTimestamp === null ? undefined : { unixTimestampMillis: recordingTimestamp }
    )

    return (
        <div className="flex h-full min-w-0 flex-col overflow-hidden">
            <SubHeader className="shrink-0 justify-end">
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
