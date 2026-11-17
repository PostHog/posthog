import { type ReactElement, useState } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { plural } from '@/model/adapters/text'
import type { QueryState } from '@/model/types'
import { Eyebrow } from '@/ui/Eyebrow'
import { MonoText } from '@/ui/MonoText'
import { Pressable44 } from '@/ui/Pressable44'
import { TimelineItem } from '@/ui/TimelineItem'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import type { SessionTimeline, TimelineEntry } from './replayModel'
import { formatOffset, nearestEntryKey } from './sessionAdapters'

/** Entries shown before "Show more", so the timeline does not push the rest of the screen away. */
const FIRST_ENTRIES = 25

interface SessionTimelineSectionProps {
    timeline: QueryState<SessionTimeline>
    /** Milliseconds into the recording that the link pointed at; the nearest row is highlighted. */
    highlightMs?: number
    onOpenIssue: (issueId: string) => void
}

export function SessionTimelineSection({
    timeline,
    highlightMs,
    onOpenIssue,
}: SessionTimelineSectionProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const [expanded, setExpanded] = useState(false)
    const data = timeline.data
    return (
        <View style={styles.section} testID="session-timeline">
            <View style={styles.header}>
                <Eyebrow>What happened</Eyebrow>
                {data ? (
                    <Text style={styles.count}>
                        {data.truncated ? `${data.eventCount}+ events` : plural(data.eventCount, 'event')}
                    </Text>
                ) : null}
            </View>
            {timeline.isError ? (
                <View style={styles.message}>
                    <Text style={styles.messageText}>Couldn't load this session's events.</Text>
                    <Pressable44
                        onPress={() => void timeline.refetch()}
                        accessibilityRole="button"
                        pressedBackground={colors.sunken}
                        style={styles.retry}
                        testID="session-timeline-retry"
                    >
                        <Text style={styles.retryText}>Try again</Text>
                    </Pressable44>
                </View>
            ) : !data ? (
                <View style={styles.loading} accessibilityLabel="Loading events" accessibilityRole="progressbar">
                    <ActivityIndicator color={colors.tertiary} />
                </View>
            ) : data.groups.length === 0 ? (
                <Text style={styles.messageText}>No page views, clicks or errors were captured in this session.</Text>
            ) : (
                <Groups
                    timeline={data}
                    highlightKey={highlightMs === undefined ? null : nearestEntryKey(data, highlightMs)}
                    expanded={expanded}
                    onExpand={() => setExpanded(true)}
                    onOpenIssue={onOpenIssue}
                />
            )}
        </View>
    )
}

interface GroupsProps {
    timeline: SessionTimeline
    highlightKey: string | null
    expanded: boolean
    onExpand: () => void
    onOpenIssue: (issueId: string) => void
}

function Groups({ timeline, highlightKey, expanded, onExpand, onOpenIssue }: GroupsProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const all = timeline.groups.flatMap((group) => group.entries)
    const total = all.length
    // The row the link points at is always on screen, even past the first rows.
    const highlightIndex = all.findIndex((entry) => entry.key === highlightKey)
    let budget = expanded ? total : Math.max(FIRST_ENTRIES, highlightIndex + 1)
    const groups = timeline.groups.flatMap((group) => {
        if (budget <= 0) {
            return []
        }
        const entries = group.entries.slice(0, budget)
        budget -= entries.length
        return [{ ...group, entries }]
    })
    const shown = groups.reduce((sum, group) => sum + group.entries.length, 0)
    const lastGroup = groups[groups.length - 1]
    const lastKey = lastGroup?.entries[lastGroup.entries.length - 1]?.key
    return (
        <View>
            {groups.map((group) => (
                <View key={group.startMs}>
                    <MonoText color={colors.tertiary} style={styles.minute}>
                        {formatOffset(group.startMs)}
                    </MonoText>
                    {group.entries.map((entry) => (
                        <Entry
                            key={entry.key}
                            entry={entry}
                            isLast={entry.key === lastKey}
                            highlighted={entry.key === highlightKey}
                            onOpenIssue={onOpenIssue}
                        />
                    ))}
                </View>
            ))}
            {shown < total ? (
                <Pressable44
                    onPress={onExpand}
                    accessibilityRole="button"
                    pressedBackground={colors.sunken}
                    style={styles.more}
                    testID="session-timeline-more"
                >
                    <Text style={styles.moreText}>{`Show ${total - shown} more`}</Text>
                </Pressable44>
            ) : null}
        </View>
    )
}

function Entry({
    entry,
    isLast,
    highlighted,
    onOpenIssue,
}: {
    entry: TimelineEntry
    isLast: boolean
    highlighted: boolean
    onOpenIssue: (issueId: string) => void
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const alert = entry.kind === 'exception' || entry.kind === 'rageclick'
    const item = (
        <TimelineItem
            text={entry.text}
            via={entry.event}
            time={formatOffset(entry.offsetMs)}
            isLast={isLast}
            alert={alert}
        />
    )
    const { issueId } = entry
    if (!issueId) {
        return highlighted ? (
            <View style={styles.highlight} testID="session-timeline-highlight">
                {item}
            </View>
        ) : (
            item
        )
    }
    return (
        <Pressable44
            onPress={() => onOpenIssue(issueId)}
            accessibilityRole="link"
            accessibilityHint="Opens the error"
            pressedBackground={colors.sunken}
            style={highlighted ? styles.highlight : undefined}
            testID="session-timeline-issue"
        >
            {item}
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    section: {
        marginTop: 28,
    },
    highlight: {
        marginHorizontal: -8,
        paddingHorizontal: 8,
        paddingTop: 6,
        borderRadius: radii.card,
        backgroundColor: colors.sunken,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 10,
    },
    count: {
        ...type.meta,
        color: colors.tertiary,
    },
    minute: {
        marginLeft: 26,
        marginBottom: 8,
    },
    loading: {
        minHeight: 80,
        alignItems: 'center',
        justifyContent: 'center',
    },
    message: {
        gap: 10,
        alignItems: 'flex-start',
    },
    messageText: {
        ...type.bodySmall,
        color: colors.muted,
    },
    retry: {
        minHeight: 36,
        paddingHorizontal: 14,
        justifyContent: 'center',
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
    },
    retryText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    more: {
        marginTop: 4,
        alignSelf: 'flex-start',
        minHeight: 36,
        paddingHorizontal: 14,
        justifyContent: 'center',
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
    },
    moreText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
}))
