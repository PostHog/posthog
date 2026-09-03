import { useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

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
    const { recordingProps, recordingTimestamp, isTimestampOutsideRecording, sessionId } = useValues(sessionTabLogic)

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
