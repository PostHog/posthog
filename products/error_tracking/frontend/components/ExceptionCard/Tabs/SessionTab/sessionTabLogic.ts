import { actions, connect, defaults, events, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'

import { Dayjs, dayjs } from 'lib/dayjs'
import { SessionRecordingPlayerProps } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

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
            ['isNotFound', 'sessionPlayerMetaDataLoading'],
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
    }),

    reducers({
        recordingTimestamp: {
            setRecordingTimestamp: (_, { timestamp, offset }: { timestamp: Dayjs; offset: number }) =>
                dayjs(timestamp).valueOf() - offset,
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
    }),
    events(({ props, actions }) => ({
        afterMount: () => {
            actions.setRecordingTimestamp(dayjs(props.timestamp), 5000)
        },
    })),
])
