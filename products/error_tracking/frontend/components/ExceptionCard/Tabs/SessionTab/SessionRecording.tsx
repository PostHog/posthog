import { Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { TabsPrimitiveContent } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { useLayoutEffect, useMemo } from 'react'
import {
    SessionRecordingPlayer,
    SessionRecordingPlayerProps,
} from 'scenes/session-recordings/player/SessionRecordingPlayer'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerMode,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { exceptionCardLogic } from '../../exceptionCardLogic'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { match } from 'ts-pattern'
import { SessionTabProps } from '.'
import { sessionTabLogic } from './sessionTabLogic'

export function SessionRecording({ ...props }: SessionTabProps): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    return (
        <TabsPrimitiveContent {...props}>
            {match(loading)
                .with(true, () => <SessionRecordingLoading />)
                .with(false, () => <SessionRecordingContent />)
                .exhaustive()}
        </TabsPrimitiveContent>
    )
}

export function SessionRecordingLoading(): JSX.Element {
    return (
        <div className="flex justify-center w-full h-[300px] items-center">
            <Spinner />
        </div>
    )
}

export function SessionRecordingNoSession(): JSX.Element {
    return (
        <div className="flex justify-center w-full h-[300px] items-center">
            <EmptyMessage
                title="No session available"
                description="There is not $session_id associated with this exception."
                buttonText="Check doc"
                buttonTo="https://posthog.com/docs/data/sessions"
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

export function SessionRecordingContent(): JSX.Element {
    const { sessionId, timestamp } = useValues(sessionTabLogic)
    const recordingProps = useMemo(() => getRecordingProps(sessionId), [sessionId])
    const playerLogic = sessionRecordingPlayerLogic(recordingProps)
    const { seekToTimestamp, setPlay } = useActions(playerLogic)

    useLayoutEffect(() => {
        if (timestamp) {
            const fiveSecondsBefore = dayjs(timestamp).valueOf() - 5000
            seekToTimestamp(fiveSecondsBefore, false)
        }
    }, [timestamp, seekToTimestamp, setPlay])

    return (
        <div className="max-h-[500px] h-[500px] flex justify-center items-center">
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
