import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { match } from 'ts-pattern'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { TabsPrimitiveContent } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { exceptionCardLogic } from '../../exceptionCardLogic'
import { sessionTabLogic } from './sessionTabLogic'

export function SessionRecordingTab(): JSX.Element {
    const { loading } = useValues(exceptionCardLogic)
    return (
        <TabsPrimitiveContent value="recording" className="flex-1 min-h-0 overflow-y-auto">
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
    const {
        recordingProps,
        recordingTimestamp,
        isNotFound,
        sessionPlayerMetaDataLoading,
        isTimestampOutsideRecording,
    } = useValues(sessionTabLogic)
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
        <div className="h-full flex flex-col">
            {isTimestampOutsideRecording && (
                <LemonBanner type="info" className="m-2">
                    The exception occurred outside the recorded session timeframe. It is attached to a session but not
                    visible in the recording.
                </LemonBanner>
            )}
            <div className="flex-1 flex justify-center items-center min-h-0">
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
