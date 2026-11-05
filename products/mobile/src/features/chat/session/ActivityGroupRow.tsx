import { memo, type ReactElement, useEffect, useState } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'
import Animated, { useAnimatedStyle, useReducedMotion, useSharedValue, withTiming } from 'react-native-reanimated'

import { track } from '@/lib/analytics'
import { Dot } from '@/ui/Dot'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { MonoText } from '@/ui/MonoText'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, type ThemeColors, useColors } from '@/ui/theme'
import { iconSizes, motion, type } from '@/ui/tokens'

import { ChatMarkdown } from '../ChatMarkdown'
import { isActivityRunning, summarizeActivity } from './sessionDisplay'
import type { SessionActivityGroup, SessionThoughtItem, SessionToolInvocation } from './types'

interface ActivityGroupRowProps {
    group: SessionActivityGroup
    invocations: ReadonlyMap<string, SessionToolInvocation>
    /** The call a pending decision waits on, which the row must not count as running. */
    waitingToolCallId?: string
}

function toolDotColor(invocation: SessionToolInvocation, colors: ThemeColors): string {
    switch (invocation.status) {
        case 'pending':
        case 'in_progress':
            return colors.blue
        case 'failed':
            return colors.orange
        case 'completed':
            return colors.tertiary
    }
}

function ToolRow({ invocation }: { invocation: SessionToolInvocation }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.toolRow} testID={`session-tool-${invocation.toolCallId}`}>
            <View style={styles.toolDot}>
                <Dot color={toolDotColor(invocation, colors)} size={6} />
            </View>
            <View style={styles.toolBody}>
                <MonoText color={colors.muted} numberOfLines={1}>
                    {invocation.title ?? invocation.toolName}
                </MonoText>
                {invocation.detail ? (
                    <Text style={styles.toolNote} numberOfLines={2}>
                        {invocation.detail}
                    </Text>
                ) : null}
                {invocation.status === 'failed' && invocation.errorMessage ? (
                    <Text style={styles.toolNote} numberOfLines={2}>
                        {invocation.errorMessage}
                    </Text>
                ) : null}
            </View>
        </View>
    )
}

function ThoughtRow({ item }: { item: SessionThoughtItem }): ReactElement | null {
    const styles = useStyles()
    return item.text ? (
        <View style={styles.thought}>
            <ChatMarkdown tone="thought" text={item.text} streaming={!item.complete} />
        </View>
    ) : null
}

function ActivityGroupRowImpl({ group, invocations, waitingToolCallId }: ActivityGroupRowProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const running = isActivityRunning(group, invocations, waitingToolCallId)
    const summary = summarizeActivity(group, invocations, waitingToolCallId)
    // Every group starts closed, also while it runs; the summary line carries the progress.
    const [expanded, setExpanded] = useState(false)
    const toggle = (): void => {
        if (!expanded) {
            track('mobile_chat_activity_expanded', {
                running,
                tool_count: group.items.filter((item) => item.kind === 'tool').length,
            })
        }
        setExpanded(!expanded)
    }

    const reduceMotion = useReducedMotion()
    const rotation = useSharedValue(expanded ? 180 : 0)
    useEffect(() => {
        rotation.value = withTiming(expanded ? 180 : 0, { duration: reduceMotion ? 0 : motion.chevron })
    }, [expanded, reduceMotion, rotation])
    const chevronStyle = useAnimatedStyle(() => ({ transform: [{ rotate: `${rotation.value}deg` }] }))

    return (
        <View style={styles.group} testID={`session-activity-${group.id}`}>
            <Pressable44
                onPress={toggle}
                accessibilityLabel={summary}
                accessibilityState={{ expanded }}
                style={styles.header}
            >
                <View style={styles.indicator}>
                    {running ? (
                        <ActivityIndicator size="small" color={colors.tertiary} />
                    ) : (
                        <Dot color={colors.tertiary} size={6} />
                    )}
                </View>
                <Text style={styles.summary} numberOfLines={1}>
                    {summary}
                </Text>
                <Animated.View style={chevronStyle}>
                    <ChevronDownIcon size={iconSizes.inline} color={colors.tertiary} />
                </Animated.View>
            </Pressable44>
            {expanded ? (
                <View style={styles.details}>
                    {group.items.map((item) => {
                        if (item.kind === 'thought') {
                            return <ThoughtRow key={item.id} item={item} />
                        }
                        const invocation = invocations.get(item.toolCallId)
                        return invocation ? <ToolRow key={item.id} invocation={invocation} /> : null
                    })}
                </View>
            ) : null}
        </View>
    )
}

// The invocations map changes on every tool update, so a settled group skips a render when its own calls did not change.
function sameRow(previous: ActivityGroupRowProps, next: ActivityGroupRowProps): boolean {
    return (
        previous.waitingToolCallId === next.waitingToolCallId &&
        previous.group.id === next.group.id &&
        previous.group.items.length === next.group.items.length &&
        previous.group.items.every((item, index) => {
            const other = next.group.items[index]
            if (item !== other) {
                return false
            }
            return (
                item.kind !== 'tool' ||
                previous.invocations.get(item.toolCallId) === next.invocations.get(item.toolCallId)
            )
        })
    )
}

export const ActivityGroupRow = memo(ActivityGroupRowImpl, sameRow)

const useStyles = createStyles(({ colors }) => ({
    group: {
        gap: 4,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        minHeight: 32,
    },
    indicator: {
        width: 20,
        height: 20,
        alignItems: 'center',
        justifyContent: 'center',
    },
    summary: {
        ...type.bodySmall,
        color: colors.muted,
        flexShrink: 1,
    },
    details: {
        marginLeft: 9,
        paddingLeft: 18,
        borderLeftWidth: 1,
        borderLeftColor: colors.hairline,
        gap: 8,
        paddingVertical: 2,
    },
    toolRow: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 8,
    },
    toolDot: {
        height: 19,
        justifyContent: 'center',
    },
    toolBody: {
        flex: 1,
        minWidth: 0,
    },
    toolNote: {
        ...type.meta,
        color: colors.muted,
        marginTop: 2,
    },
    thought: {
        // Markdown blocks end with a 10pt bottom margin; this keeps the details gap even.
        marginBottom: -10,
    },
}))
