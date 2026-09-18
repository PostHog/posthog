import { useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
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
    const { properties, recordingStatus } = useValues(errorPropertiesLogic)
    const { recordingProps, recordingTimestamp, isTimestampOutsideRecording, sessionId } = useValues(sessionTabLogic)

    // The event already carries why replay was not running when it was captured. Say that, rather
    // than mounting a player that can only 404 and then explain the miss in project-wide terms.
    // A recorder that reports itself off can still sit in a session recorded earlier, so a known
    // recording always wins and the player stays.
    const hasRecording = properties?.$has_recording as boolean | undefined
    const noRecordingReason =
        hasRecording === true ? null : recordingDisabledReason(sessionId, recordingStatus, hasRecording)

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
