import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Button, TabsContent } from 'lib/ui/quill'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { SubHeader } from '../SubHeader'
import { RecordingEdge, sessionTabLogic } from './sessionTabLogic'

const OUTSIDE_RECORDING_COPY: Record<RecordingEdge, string> = {
    start: 'This exception happened before the recording starts. Playback begins at the first frame, so you will not see the exception itself.',
    end: 'This exception happened after the recording ends. Playback stays on the last frame, so you will not see the exception itself.',
}

export function SessionRecordingTab(): JSX.Element {
    return (
        <TabsContent value="recording" className="min-h-0 min-w-0 flex-1 overflow-y-auto">
            <SessionRecordingContent />
        </TabsContent>
    )
}

export function SessionRecordingContent(): JSX.Element {
    const { recordingProps, recordingTimestamp, exceptionOutsideEdge, sessionId } = useValues(sessionTabLogic)

    useEffect(() => {
        if (exceptionOutsideEdge) {
            posthog.capture('error_tracking_recording_outside_session', {
                sessionId,
                edge: exceptionOutsideEdge,
            })
        }
    }, [exceptionOutsideEdge, sessionId])

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
            {exceptionOutsideEdge && (
                <LemonBanner type="info" className="m-2">
                    {OUTSIDE_RECORDING_COPY[exceptionOutsideEdge]}
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
