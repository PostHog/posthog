import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { match } from 'ts-pattern'

import { Spinner } from '@posthog/lemon-ui'

import { TabsPrimitiveContent } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { exceptionCardLogic } from '../../exceptionCardLogic'
import { sessionTabLogic } from './sessionTabLogic'

export function SessionRecordingTab(): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    return (
        <TabsPrimitiveContent value="recording">
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
    const { recordingProps, recordingTimestamp, isNotFound, sessionPlayerMetaDataLoading } = useValues(sessionTabLogic)
    const { seekToTimestamp, setPlay } = useActions(sessionTabLogic)

    useEffect(() => {
        if (sessionPlayerMetaDataLoading || isNotFound) {
            return
        }
        if (recordingTimestamp) {
            seekToTimestamp(recordingTimestamp)
        }
        setPlay()
    }, [seekToTimestamp, recordingTimestamp, setPlay, isNotFound, sessionPlayerMetaDataLoading])

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
