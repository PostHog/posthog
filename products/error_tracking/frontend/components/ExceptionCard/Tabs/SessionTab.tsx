import { Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { dayjs } from 'lib/dayjs'
import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { useLayoutEffect, useMemo } from 'react'
import {
    SessionRecordingPlayer,
    SessionRecordingPlayerProps,
} from 'scenes/session-recordings/player/SessionRecordingPlayer'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { exceptionCardLogic } from '../exceptionCardLogic'

export interface SessionTabProps extends TabsPrimitiveContentProps {
    timestamp?: string
}

function getRecordingProps(sessionId: string): SessionRecordingPlayerProps {
    return {
        playerKey: `session-tab`,
        sessionRecordingId: sessionId,
        matchingEventsMatchType: {
            matchType: 'name',
            eventNames: ['$exception'],
        },
    }
}

export function SessionTab({ timestamp, ...props }: SessionTabProps): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    const { sessionId } = useValues(errorPropertiesLogic)
    const recordingProps = useMemo(() => getRecordingProps(sessionId!), [sessionId])
    const playerLogic = sessionRecordingPlayerLogic(recordingProps)
    const { seekToTimestamp, setPlay, setPause } = useActions(playerLogic)

    useLayoutEffect(() => {
        if (timestamp && sessionId) {
            const five_seconds_before = dayjs(timestamp).valueOf() - 5000
            seekToTimestamp(five_seconds_before, false)
            setPlay()
        } else {
            setPause()
        }
    }, [timestamp, seekToTimestamp, setPlay, sessionId])

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
                        autoPlay={true}
                        noMeta
                        noBorder
                        noInspector
                    />
                </div>
            )}
        </TabsPrimitiveContent>
    )
}
