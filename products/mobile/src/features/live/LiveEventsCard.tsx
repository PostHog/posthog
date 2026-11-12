import { type ReactElement, useEffect, useRef } from 'react'
import { StyleSheet, Text, View } from 'react-native'
import Animated, { useAnimatedStyle, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated'

import { useNow } from '@/lib/useNow'
import type { LiveEventRow } from '@/model/live'
import { DocumentIcon } from '@/ui/icons/DocumentIcon'
import { PhoneIcon } from '@/ui/icons/PhoneIcon'
import { SparklesIcon } from '@/ui/icons/SparklesIcon'
import { MonoText } from '@/ui/MonoText'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { type } from '@/ui/tokens'

import { LiveCard, LiveCardNote, NOT_LOADED_TEXT } from './LiveCard'
import { agoText } from './liveFormat'

const HIGHLIGHT_MS = 1500
const SLIDE_PX = 10

interface LiveEventsCardProps {
    events: LiveEventRow[] | null
    screenActive: boolean
    onOpen: (event: LiveEventRow) => void
}

/** The newest 50 events, newest first. Events that arrive after the first read slide in with a short highlight. */
export function LiveEventsCard({ events, onOpen, screenActive }: LiveEventsCardProps): ReactElement {
    const now = useNow(screenActive ? 10_000 : null).getTime()
    const seen = useRef<Set<string> | null>(null)
    const previous = seen.current
    useEffect(() => {
        if (events) {
            seen.current = new Set(events.map((event) => event.id))
        }
    }, [events])
    let body: ReactElement
    if (!events) {
        body = <LiveCardNote text={NOT_LOADED_TEXT} testID="live-events-not-loaded" />
    } else if (events.length === 0) {
        body = <LiveCardNote text="Waiting for events…" testID="live-events-empty" />
    } else {
        body = (
            <View>
                {events.map((event, index) => (
                    <EventRow
                        key={event.id}
                        event={event}
                        now={now}
                        fresh={previous !== null && !previous.has(event.id)}
                        onOpen={onOpen}
                        testID={`live-event-${index}`}
                    />
                ))}
            </View>
        )
    }
    return (
        <LiveCard title="Live events" meta="Newest first" flush testID="live-events">
            {body}
        </LiveCard>
    )
}

function EventIcon({ event, color }: { event: LiveEventRow; color: string }): ReactElement {
    switch (event.kind) {
        case 'pageview':
            return <DocumentIcon size={18} color={color} />
        case 'screen':
            return <PhoneIcon size={18} color={color} />
        case 'other':
            return <SparklesIcon size={18} color={color} />
    }
}

function EventRow({
    event,
    now,
    fresh,
    onOpen,
    testID,
}: {
    event: LiveEventRow
    now: number
    fresh: boolean
    onOpen: (event: LiveEventRow) => void
    testID: string
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const reduced = useReducedMotion()
    const highlight = useSharedValue(fresh ? 1 : 0)
    const slide = useSharedValue(fresh && !reduced ? 1 : 0)
    useEffect(() => {
        highlight.value = withTiming(0, { duration: HIGHLIGHT_MS })
        slide.value = withTiming(0, { duration: 300 })
    }, [highlight, slide])
    const highlightStyle = useAnimatedStyle(() => ({ opacity: highlight.value }))
    const slideStyle = useAnimatedStyle(() => ({
        opacity: 1 - slide.value,
        transform: [{ translateY: -SLIDE_PX * slide.value }],
    }))
    const when = Number.isFinite(event.at) ? agoText(event.at, now) : ''
    return (
        <Animated.View style={slideStyle}>
            <Pressable44
                onPress={() => onOpen(event)}
                accessibilityLabel={`${event.label}${event.place ? `, ${event.place}` : ''}${when ? `, ${when}` : ''}`}
                accessibilityHint="Opens the event details"
                pressedBackground={colors.pressed}
                style={styles.row}
                testID={testID}
            >
                <Animated.View
                    pointerEvents="none"
                    style={[StyleSheet.absoluteFill, { backgroundColor: colors.blueHighlight }, highlightStyle]}
                />
                <View style={styles.icon}>
                    <EventIcon event={event} color={colors.secondary} />
                </View>
                <View style={styles.main}>
                    <Text style={styles.name} numberOfLines={1}>
                        {event.label}
                    </Text>
                    {event.place ? (
                        <Text style={styles.place} numberOfLines={1}>
                            {event.place}
                        </Text>
                    ) : null}
                </View>
                <View style={styles.side}>
                    <Text style={styles.when} numberOfLines={1}>
                        {when}
                    </Text>
                    <MonoText size={11} color={colors.tertiary} numberOfLines={1} style={styles.person}>
                        {event.distinctId}
                    </MonoText>
                </View>
            </Pressable44>
        </Animated.View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        minHeight: 60,
        paddingHorizontal: 14,
        paddingVertical: 10,
        borderTopWidth: 1,
        borderTopColor: colors.rowDivider,
    },
    icon: {
        width: 20,
        alignItems: 'center',
    },
    main: {
        flex: 1,
        minWidth: 0,
        gap: 2,
    },
    name: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    place: {
        ...type.meta,
        color: colors.secondary,
    },
    side: {
        alignItems: 'flex-end',
        gap: 2,
        maxWidth: '42%',
    },
    when: {
        ...type.meta,
        color: colors.tertiary,
    },
    person: {
        maxWidth: '100%',
    },
}))
