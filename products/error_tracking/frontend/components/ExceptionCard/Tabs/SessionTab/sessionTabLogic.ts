import { actions, connect, defaults, events, kea, key, path, props, reducers, selectors, propsChanged } from 'kea'

import type { sessionTabLogicType } from './sessionTabLogicType'
import { dayjs } from 'lib/dayjs'
import {
    SessionTimelineEvent,
    SessionTimelineItem,
    SessionTimelineRenderer,
    RendererGroup,
} from './SessionTimelineItem/base'
import {
    eventRenderer,
    exceptionRenderer,
    featureFlagRenderer,
    pageRenderer,
    surveysRenderer,
    webAnalyticsRenderer,
} from './SessionTimelineItem/event'
import { SessionRecordingPlayerProps } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

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

export type RendererRegistry = SessionTimelineRenderer<SessionTimelineItem>[]

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
        actions: [
            sessionRecordingPlayerLogic(getRecordingProps(sessionId)),
            ['seekToTimestamp', 'setPlay', 'setPause'],
        ],
    })),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.timestamp !== oldProps.timestamp) {
            actions.setRecordingTimestamp(props.timestamp, 5000)
        }
    }),

    actions({
        registerRenderer: (renderer: SessionTimelineRenderer<SessionTimelineItem>) => ({
            renderer,
        }),
        toggleGroup: (name: RendererGroup) => ({ name }),
        setRecordingTimestamp: (timestamp: string, offset: number) => ({ timestamp, offset }),
        loadEvents: true,
        setEvents: (events: SessionTimelineEvent[]) => ({ events }),
    }),

    defaults({
        activeGroups: [] as RendererGroup[],
        rendererRegistry: [] as RendererRegistry,
        recordingTimestamp: null as number | null,
        events: [] as SessionTimelineEvent[],
        filteredItems: [] as [SessionTimelineItem, SessionTimelineRenderer<SessionTimelineItem>][],
    }),

    reducers({
        rendererRegistry: {
            registerRenderer: (state, { renderer }: { renderer: SessionTimelineRenderer<SessionTimelineItem> }) => [
                ...state,
                renderer,
            ],
        },
        activeGroups: {
            registerRenderer: (state, { renderer }: { renderer: SessionTimelineRenderer<SessionTimelineItem> }) => [
                ...state,
                renderer.group,
            ],
            toggleGroup: (state, { name }: { name: RendererGroup }) => {
                if (state.includes(name)) {
                    return state.filter((r: RendererGroup) => r !== name)
                }
                return [...state, name]
            },
        },
        recordingTimestamp: {
            setRecordingTimestamp: (_, { timestamp, offset }: { timestamp: string; offset: number }) =>
                dayjs(timestamp).valueOf() - offset,
        },
        events: {
            setEvents: (_, { events }: { events: SessionTimelineEvent[] }) => events,
        },
    }),
    selectors({
        sessionId: [() => [(_, props) => props.sessionId], (sessionId: string) => sessionId],
        timestamp: [() => [(_, props) => props.timestamp], (timestamp: string) => timestamp],
        items: [
            (s) => [s.events, s.rendererRegistry],
            (
                events: SessionTimelineEvent[],
                rendererRegistry: RendererRegistry
            ): [SessionTimelineItem, SessionTimelineRenderer<SessionTimelineItem> | undefined][] => {
                function getRenderer(
                    item: SessionTimelineItem
                ): SessionTimelineRenderer<SessionTimelineItem> | undefined {
                    return rendererRegistry.find((renderer) => renderer.predicate(item))
                }
                return events.map((event) => [event, getRenderer(event)])
            },
        ],
        filteredItems: [
            (s) => [s.items, s.activeGroups],
            (items: [SessionTimelineItem, SessionTimelineRenderer<SessionTimelineItem>][], activeGroups: string[]) => {
                return items.filter(([_, renderer]) => !!renderer && activeGroups.includes(renderer.group))
            },
        ],
        isGroupActive: [
            (s) => [s.activeGroups],
            (activeGroups: string[]) => {
                return (group: string) => activeGroups.includes(group)
            },
        ],
        usedGroups: [
            (s) => [s.items],
            (items: [SessionTimelineItem, SessionTimelineRenderer<SessionTimelineItem> | undefined][]) => {
                const orderedRenderers = Object.values(RendererGroup)
                const usedGroupsSet = items.reduce((acc, [_, renderer]) => {
                    if (!renderer) {
                        return acc
                    }
                    acc.add(renderer.group)
                    return acc
                }, new Set<RendererGroup>())
                return Array.from(usedGroupsSet).sort(
                    (a, b) => orderedRenderers.indexOf(a) - orderedRenderers.indexOf(b)
                )
            },
        ],
        recordingProps: [
            () => [(_, props) => props.sessionId],
            (sessionId: string) => {
                return getRecordingProps(sessionId)
            },
        ],
    }),
    events(({ props, actions }) => ({
        afterMount: () => {
            actions.registerRenderer(exceptionRenderer)
            actions.registerRenderer(featureFlagRenderer)
            actions.registerRenderer(pageRenderer)
            actions.registerRenderer(surveysRenderer)
            actions.registerRenderer(webAnalyticsRenderer)
            actions.registerRenderer(eventRenderer)
            actions.setRecordingTimestamp(props.timestamp, 5000)
        },
    })),
])
