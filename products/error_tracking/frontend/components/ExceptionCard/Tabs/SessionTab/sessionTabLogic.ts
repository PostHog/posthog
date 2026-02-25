import { actions, connect, defaults, events, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'

import { Dayjs, dayjs } from 'lib/dayjs'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { SessionRecordingPlayerProps } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { SessionPlayerData } from '~/types'

import type { sessionTabLogicType } from './sessionTabLogicType'

export type SessionTabLogicProps = {
    sessionId: string
    timestamp: string
}

export type TabId = 'recording' | 'timeline'

export type TimelineEvent = {
    uuid: string
    event: string
    timestamp: string
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

export const sessionTabLogic = kea<sessionTabLogicType>([
    path((key) => ['scenes', 'error-tracking', 'exceptionCard', 'sessionTab', key]),
    props({} as SessionTabLogicProps),
    key(({ sessionId }) => sessionId as KeyType),
    connect(({ sessionId }: SessionTabLogicProps) => ({
        values: [
            sessionRecordingDataCoordinatorLogic(getRecordingProps(sessionId)),
            ['isNotFound', 'sessionPlayerMetaDataLoading', 'sessionPlayerData'],
        ],
        actions: [
            sessionRecordingPlayerLogic(getRecordingProps(sessionId)),
            ['seekToTimestamp', 'setPlay', 'setPause'],
        ],
    })),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.timestamp !== oldProps.timestamp) {
            actions.setRecordingTimestamp(dayjs(props.timestamp), 5000)
        }
    }),

    actions({
        setRecordingTimestamp: (timestamp: Dayjs, offset: number) => ({ timestamp, offset }),
    }),

    defaults({
        recordingTimestamp: null as number | null,
        exceptionTimestamp: null as number | null,
    }),

    reducers({
        recordingTimestamp: {
            setRecordingTimestamp: (_, { timestamp, offset }: { timestamp: Dayjs; offset: number }) =>
                dayjs(timestamp).valueOf() - offset,
        },
        exceptionTimestamp: {
            setRecordingTimestamp: (_, { timestamp }: { timestamp: Dayjs }) => dayjs(timestamp).valueOf(),
        },
    }),
    selectors({
        sessionId: [(_, p) => [p.sessionId], (sessionId) => sessionId],
        timestamp: [(_, p) => [p.timestamp], (timestamp) => timestamp],
        recordingProps: [
            (_, p) => [p.sessionId],
            (sessionId) => {
                return getRecordingProps(sessionId)
            },
        ],
        isTimestampOutsideRecording: [
            (s) => [s.exceptionTimestamp, s.sessionPlayerData, s.sessionPlayerMetaDataLoading],
            (
                exceptionTimestamp: number | null,
                sessionPlayerData: SessionPlayerData,
                sessionPlayerMetaDataLoading: boolean
            ): boolean => {
                if (
                    sessionPlayerMetaDataLoading ||
                    exceptionTimestamp === null ||
                    !sessionPlayerData.start ||
                    !sessionPlayerData.end
                ) {
                    return false
                }
                return (
                    exceptionTimestamp < sessionPlayerData.start.valueOf() ||
                    exceptionTimestamp > sessionPlayerData.end.valueOf()
                )
            },
        ],
    }),
    events(({ props, actions }) => ({
        afterMount: () => {
            actions.setRecordingTimestamp(dayjs(props.timestamp), 5000)
        },
    })),
])
