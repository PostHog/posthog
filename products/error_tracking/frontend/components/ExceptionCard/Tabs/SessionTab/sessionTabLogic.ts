import { actions, connect, defaults, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import type { sessionTabLogicType } from './sessionTabLogicType'
import { loaders } from 'kea-loaders'
import { hogql } from '~/queries/utils'
import { dayjs } from 'lib/dayjs'
import api from 'lib/api'
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
        actions: [sessionRecordingPlayerLogic(getRecordingProps(sessionId)), ['seekToTimestamp']],
    })),

    actions({
        setCurrentTab: (tab: TabId) => ({ tab }),
        setEventListEl: (eventListEl: React.RefObject<HTMLDivElement>) => ({ eventListEl }),
        scrollToItem: (itemId: string) => ({ itemId }),
        registerRenderer: (renderer: SessionTimelineRenderer<SessionTimelineItem>) => ({
            renderer,
        }),
        toggleGroup: (name: RendererGroup) => ({ name }),
        goToTimestamp: (timestamp: string, offset: number) => ({ timestamp, offset }),
        loadEvents: true,
    }),

    defaults({
        currentTab: 'timeline',
        setEventListEl: null as HTMLDivElement | null,
        activeGroups: [] as RendererGroup[],
        rendererRegistry: [] as RendererRegistry,
    }),

    reducers({
        currentTab: {
            setCurrentTab: (_, { tab }: { tab: string }) => tab,
        },
        eventListEl: {
            setEventListEl: (_, { eventListEl }: { eventListEl: React.RefObject<HTMLDivElement> }) => eventListEl,
        },
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
    }),

    loaders(({ props }) => ({
        events: [
            [] as SessionTimelineEvent[],
            {
                loadEvents: async () => {
                    const start = dayjs(props.timestamp).subtract(5, 'minutes')
                    const end = dayjs(props.timestamp).add(5, 'minutes')
                    const sessionEventsQuery = hogql`
                    SELECT uuid, event, timestamp, properties
                    FROM events
                    WHERE timestamp > ${start}
                    AND timestamp < ${end}
                    AND $session_id = ${props.sessionId}
                    ORDER BY timestamp ASC
                    LIMIT 1000000`

                    const response = await api.queryHogQL(sessionEventsQuery)
                    return response.results.map((result: any) => ({
                        id: result[0],
                        type: 'event',
                        timestamp: result[2],
                        payload: {
                            event: result[1],
                            properties: JSON.parse(result[3]),
                        },
                    }))
                },
            },
        ],
    })),
    listeners(({ values }) => ({
        scrollToItem: ({ itemId }) => {
            const eventListEl = values.eventListEl
            if (eventListEl) {
                const eventEl = eventListEl.querySelector(`[data-item-id="${itemId}"]`)
                if (eventEl) {
                    eventEl.scrollIntoView({ behavior: 'instant', block: 'center' })
                }
            }
        },
    })),
    selectors({
        sessionId: [(_, props) => [props.sessionId], (sessionId: string) => sessionId],
        timestamp: [(_, props) => [props.timestamp], (timestamp: string) => timestamp],
        items: [(s) => [s.events], (events: SessionTimelineEvent[]) => events as SessionTimelineItem[]],
        itemsLoading: [(s) => [s.eventsLoading], (eventsLoading: boolean) => eventsLoading],
        getRenderer: [
            (s) => [s.rendererRegistry, s.activeGroups],
            (rendererRegistry: RendererRegistry, activeGroups: string[]) => {
                return (item: SessionTimelineItem) => {
                    const renderer = rendererRegistry.find((renderer) => renderer.predicate(item))
                    if (!!renderer && activeGroups.includes(renderer.group)) {
                        return renderer
                    }
                    return undefined
                }
            },
        ],
        isGroupActive: [
            (s) => [s.activeGroups],
            (activeGroups: string[]) => {
                return (group: string) => activeGroups.includes(group)
            },
        ],
        usedGroups: [
            (s) => [s.rendererRegistry, s.items],
            (rendererRegistry: RendererRegistry, items: SessionTimelineItem[]) => {
                const orderedRenderers = Object.values(RendererGroup)

                const usedGroups = new Set<RendererGroup>()
                for (const item of items) {
                    const renderer = rendererRegistry.find((renderer) => renderer.predicate(item))
                    if (renderer) {
                        usedGroups.add(renderer.group)
                    }
                }
                return Array.from(usedGroups).sort((a, b) => orderedRenderers.indexOf(a) - orderedRenderers.indexOf(b))
            },
        ],
        canScrollToItem: [
            (s) => [s.items, s.getRenderer],
            (
                items: SessionTimelineItem[],
                getRenderer: (item: SessionTimelineItem) => SessionTimelineRenderer<SessionTimelineItem> | undefined
            ) => {
                return (itemId: string) => {
                    const item = items.find((i) => i.id === itemId)
                    if (!item) {
                        return false
                    }
                    return !!getRenderer(item)
                }
            },
        ],
        recordingProps: [
            (s) => [s.sessionId],
            (sessionId: string) => {
                return getRecordingProps(sessionId)
            },
        ],
    }),
    listeners(({ actions }) => ({
        goToTimestamp: ({ timestamp, offset }) => {
            // Implement logic to navigate to the specified timestamp
            const actualTimestamp = dayjs(timestamp).valueOf() - offset
            actions.seekToTimestamp(actualTimestamp, false)
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.registerRenderer(exceptionRenderer)
            actions.registerRenderer(featureFlagRenderer)
            actions.registerRenderer(pageRenderer)
            actions.registerRenderer(surveysRenderer)
            actions.registerRenderer(webAnalyticsRenderer)
            actions.registerRenderer(eventRenderer)
            actions.loadEvents()
        },
    })),
])
