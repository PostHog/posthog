import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { match } from 'ts-pattern'

import { LemonBanner, LemonButton, Link, Spinner } from '@posthog/lemon-ui'

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
    const { setCurrentSessionTab } = useActions(exceptionCardLogic)

    useEffect(() => {
        if (sessionPlayerMetaDataLoading || isNotFound) {
            return
        }
        if (recordingTimestamp) {
            seekToTimestamp(recordingTimestamp)
        }
        setPlay()
    }, [seekToTimestamp, recordingTimestamp, setPlay, isNotFound, sessionPlayerMetaDataLoading])

    // Render an in-context not-found state instead of the generic player 404, so users
    // can jump to the timeline rather than getting stuck on a dead-end page.
    if (!sessionPlayerMetaDataLoading && isNotFound) {
        return (
            <div className="h-full flex flex-col justify-center items-center p-6 text-center gap-3">
                <h3 className="title m-0">Recording not found</h3>
                <p className="text-secondary max-w-xl">
                    No replay is available for this exception. The session may have been outside your replay sampling or
                    retention window. The timeline still has the surrounding events.{' '}
                    <Link to="https://posthog.com/docs/session-replay/troubleshooting#recording-not-found">
                        Troubleshooting guide
                    </Link>
                </p>
                <LemonButton type="primary" size="small" onClick={() => setCurrentSessionTab('timeline')}>
                    View timeline
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="h-full flex flex-col">
            {isTimestampOutsideRecording && (
                <LemonBanner
                    type="info"
                    className="m-2"
                    action={{
                        children: 'View timeline',
                        onClick: () => setCurrentSessionTab('timeline'),
                    }}
                >
                    The exception occurred outside the recorded session timeframe. It is attached to a session but not
                    visible in the recording — open the timeline to see surrounding events.
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
