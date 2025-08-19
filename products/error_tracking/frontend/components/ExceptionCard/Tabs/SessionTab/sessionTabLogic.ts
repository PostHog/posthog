import { actions, connect, defaults, events, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'

import { Dayjs, dayjs } from 'lib/dayjs'
import { SessionRecordingPlayerProps } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { ItemCategory, ItemCollector, TimelineItem } from './SessionTimeline/timeline'
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
            sessionRecordingDataLogic(getRecordingProps(sessionId)),
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
        toggleCategory: (category: ItemCategory) => ({ category }),
        setRecordingTimestamp: (timestamp: Dayjs, offset: number) => ({ timestamp, offset }),
        setItems: (items: TimelineItem[]) => ({ items }),
    }),

    defaults({
        currentCategories: [
            ItemCategory.ERROR_TRACKING,
            ItemCategory.PAGE_VIEWS,
            ItemCategory.CUSTOM_EVENTS,
        ] as ItemCategory[],
        recordingTimestamp: null as number | null,
        items: [] as TimelineItem[],
        collector: null as ItemCollector | null,
    }),

    reducers({
        currentCategories: {
            toggleCategory: (state, { category }: { category: ItemCategory }) => {
                if (state.includes(category)) {
                    return state.filter((c) => c !== category)
                }
                return [...state, category]
            },
        },
        recordingTimestamp: {
            setRecordingTimestamp: (_, { timestamp, offset }: { timestamp: Dayjs; offset: number }) =>
                dayjs(timestamp).valueOf() - offset,
        },
        items: {
            setItems: (_, { items }: { items: TimelineItem[] }) => items,
        },
        collector: {
            setCollector: (_, { collector }: { collector: ItemCollector }) => collector,
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
