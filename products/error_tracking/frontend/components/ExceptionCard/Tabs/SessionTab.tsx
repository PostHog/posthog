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
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { match, P } from 'ts-pattern'

export interface SessionTabProps extends TabsPrimitiveContentProps {
    timestamp?: string
}

export function SessionTab({ timestamp, ...props }: SessionTabProps): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    const { sessionId } = useValues(errorPropertiesLogic)

    return (
        <TabsPrimitiveContent {...props}>
            {match([loading, sessionId])
                .with([true, P.any], () => <SessionTabContentLoading />)
                .with([false, P.nullish], () => <SessionTabContentNoSession />)
                .with([false, P.string], ([_, sessionId]) => (
                    <SessionTabContent sessionId={sessionId} timestamp={timestamp} />
                ))
                .otherwise(() => null)}
        </TabsPrimitiveContent>
    )
}

export function SessionTabContentLoading(): JSX.Element {
    return (
        <div className="flex justify-center w-full h-[300px] items-center">
            <Spinner />
        </div>
    )
}

export function SessionTabContentNoSession(): JSX.Element {
    return (
        <div className="flex justify-center w-full h-[300px] items-center">
            <EmptyMessage
                title="No session available"
                description="No session is associated with this exception"
                buttonText="Check documentation"
                buttonTo="https://posthog.com/docs/error-tracking/installation"
                size="small"
            />
        </div>
    )
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

export function SessionTabContent({
    timestamp,
    sessionId,
}: {
    timestamp: string | undefined
    sessionId: string
}): JSX.Element {
    const recordingProps = useMemo(() => getRecordingProps(sessionId), [sessionId])
    const playerLogic = sessionRecordingPlayerLogic(recordingProps)
    const { seekToTimestamp, setPlay } = useActions(playerLogic)

    useLayoutEffect(() => {
        if (timestamp) {
            const five_seconds_before = dayjs(timestamp).valueOf() - 5000
            seekToTimestamp(five_seconds_before, false)
        }
    }, [timestamp, seekToTimestamp, setPlay])

    return (
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
    )
}
