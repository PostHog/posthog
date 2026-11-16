import { type ReactElement, useEffect } from 'react'
import { Text, View } from 'react-native'
import Animated, {
    Easing,
    useAnimatedStyle,
    useReducedMotion,
    useSharedValue,
    withDelay,
    withTiming,
} from 'react-native-reanimated'

import { groupThousands } from '@/model/adapters/text'
import type { LiveRankedRow } from '@/model/live'
import { createStyles, useColors } from '@/ui/theme'
import { fonts, type } from '@/ui/tokens'

import { LiveCard, LiveCardNote, NOT_LOADED_TEXT } from './LiveCard'

const ROW_HEIGHT = 44
const MOVE_MS = 450
/** How long a ↑/↓ badge stays before it fades, so it marks the latest change only. */
const BADGE_MS = 4000

interface LiveRankedTableProps {
    title: string
    columnLabel: string
    rows: LiveRankedRow[] | null
    emptyText: string
    mono?: boolean
    /** Changes with every read, so a badge for the same move shows again after a later read. */
    version: number | null
    testID: string
}

/** The web's animated top list: rows slide to their new place when ranks change, with a short ↑/↓ badge. */
export function LiveRankedTable({
    title,
    columnLabel,
    rows,
    emptyText,
    mono = false,
    version,
    testID,
}: LiveRankedTableProps): ReactElement {
    const styles = useStyles()
    let body: ReactElement
    if (!rows) {
        body = <LiveCardNote text={NOT_LOADED_TEXT} testID={`${testID}-not-loaded`} />
    } else if (rows.length === 0) {
        body = <LiveCardNote text={emptyText} testID={`${testID}-empty`} />
    } else {
        body = (
            <View>
                <View style={styles.header}>
                    <Text style={styles.columnLabel}>{columnLabel}</Text>
                    <Text style={styles.columnLabel}>Views</Text>
                </View>
                <View style={{ height: rows.length * ROW_HEIGHT }}>
                    {rows.map((row, index) => (
                        <RankedRow
                            key={row.key}
                            row={row}
                            index={index}
                            mono={mono}
                            version={version}
                            testID={`${testID}-row-${index}`}
                        />
                    ))}
                </View>
            </View>
        )
    }
    return (
        <LiveCard title={title} testID={testID}>
            {body}
        </LiveCard>
    )
}

function RankedRow({
    row,
    index,
    mono,
    version,
    testID,
}: {
    row: LiveRankedRow
    index: number
    mono: boolean
    version: number | null
    testID: string
}): ReactElement {
    const styles = useStyles()
    const reduced = useReducedMotion()
    const y = useSharedValue(index * ROW_HEIGHT)
    useEffect(() => {
        const target = index * ROW_HEIGHT
        y.value = reduced ? target : withTiming(target, { duration: MOVE_MS, easing: Easing.out(Easing.cubic) })
    }, [index, reduced, y])
    const position = useAnimatedStyle(() => ({ transform: [{ translateY: y.value }] }))
    const percent = `${row.percent.toFixed(1)}%`
    const moved =
        row.rankDelta === null ? '' : `, moved ${row.rankDelta > 0 ? 'up' : 'down'} ${Math.abs(row.rankDelta)}`
    return (
        <Animated.View
            style={[styles.row, position]}
            accessible
            accessibilityLabel={`${row.label}, ${groupThousands(row.views)} views, ${percent}${moved}`}
            testID={testID}
        >
            <View style={styles.labelCell}>
                <Text
                    style={[styles.label, mono && !row.direct && styles.mono, row.direct && styles.direct]}
                    numberOfLines={1}
                    ellipsizeMode="middle"
                >
                    {row.label}
                </Text>
                {row.rankDelta !== null ? <RankBadge key={`${version ?? 0}`} delta={row.rankDelta} /> : null}
            </View>
            <Text style={styles.views} numberOfLines={1}>
                {groupThousands(row.views)}
                <Text style={styles.percent}> ({percent})</Text>
            </Text>
        </Animated.View>
    )
}

function RankBadge({ delta }: { delta: number }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const opacity = useSharedValue(1)
    useEffect(() => {
        opacity.value = withDelay(BADGE_MS, withTiming(0, { duration: 600 }))
    }, [opacity])
    const fade = useAnimatedStyle(() => ({ opacity: opacity.value }))
    const up = delta > 0
    return (
        <Animated.Text style={[styles.badge, { color: up ? colors.diffGreen : colors.diffRed }, fade]}>
            {up ? '↑' : '↓'}
            {Math.abs(delta)}
        </Animated.Text>
    )
}

const useStyles = createStyles(({ colors }) => ({
    header: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        paddingBottom: 8,
        borderBottomWidth: 1,
        borderBottomColor: colors.rowDivider,
    },
    columnLabel: {
        ...type.eyebrow,
        textTransform: 'uppercase',
        color: colors.tertiary,
    },
    row: {
        position: 'absolute',
        left: 0,
        right: 0,
        height: ROW_HEIGHT,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        borderBottomWidth: 1,
        borderBottomColor: colors.rowDivider,
    },
    labelCell: {
        flex: 1,
        minWidth: 0,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
    },
    label: {
        ...type.metaSmall,
        color: colors.ink,
        flexShrink: 1,
    },
    mono: {
        fontFamily: fonts.mono,
        fontSize: 13,
    },
    direct: {
        fontStyle: 'italic',
        color: colors.muted,
    },
    badge: {
        ...type.meta,
        fontWeight: '600',
    },
    views: {
        ...type.bodySmallStrong,
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    percent: {
        ...type.meta,
        fontWeight: '400',
        color: colors.tertiary,
    },
}))
