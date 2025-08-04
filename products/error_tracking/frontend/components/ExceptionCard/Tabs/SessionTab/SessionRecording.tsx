import { Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TabsPrimitiveContent } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { useLayoutEffect } from 'react'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { exceptionCardLogic } from '../../exceptionCardLogic'
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

export function SessionRecordingContent(): JSX.Element {
    const { recordingProps, timestamp } = useValues(sessionTabLogic)
    const { goToTimestamp } = useActions(sessionTabLogic)

    useLayoutEffect(() => {
        if (timestamp) {
            goToTimestamp(timestamp, 5000)
        }
    }, [timestamp, goToTimestamp])

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
