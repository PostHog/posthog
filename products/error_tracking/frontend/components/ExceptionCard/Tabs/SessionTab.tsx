import { Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { dayjs } from 'lib/dayjs'
import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { useEffect, useMemo } from 'react'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { exceptionCardLogic } from '../exceptionCardLogic'

export interface SessionTabProps extends TabsPrimitiveContentProps {
    timestamp?: string
}

function getRecordingProps(sessionId: string): { playerKey: string; sessionRecordingId: string } {
    return {
        playerKey: `session-tab-${sessionId}`,
        sessionRecordingId: sessionId,
    }
}

export function SessionTab({ timestamp, ...props }: SessionTabProps): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    const { sessionId, mightHaveRecording } = useValues(errorPropertiesLogic)
    const recordingProps = useMemo(() => getRecordingProps(sessionId!), [sessionId])
    const { setPause, seekToTimestamp } = useActions(sessionRecordingPlayerLogic(recordingProps))

    useEffect(() => {
        if (timestamp && mightHaveRecording) {
            const five_seconds_before = dayjs(timestamp).valueOf() - 5000
            seekToTimestamp(five_seconds_before, true)
            setPause()
        }
    }, [timestamp, mightHaveRecording, seekToTimestamp, setPause])

    return (
        <TabsPrimitiveContent {...props}>
            {loading && (
                <div className="flex justify-center w-full h-32 items-center">
                    <Spinner />
                </div>
            )}
            {!loading && (
                <div className="h-[500px]">
                    <SessionRecordingPlayer
                        {...recordingProps}
                        mode={SessionRecordingPlayerMode.Standard}
                        autoPlay={false}
                        noMeta
                        noBorder
                        noInspector
                    />
                </div>
            )}
        </TabsPrimitiveContent>
    )
}
