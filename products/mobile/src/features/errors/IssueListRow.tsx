import { memo, type ReactElement } from 'react'
import { Text, View } from 'react-native'

import type { ErrorsWindow, IssueSort } from '@/api/errorTracking'
import { SparkBars } from '@/ui/chart/SparkBars'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { AssigneeAvatar } from './AssigneeAvatar'
import { IssueBadgePill } from './IssueBadges'
import { highlightStart, ISSUE_STATS, type IssueRow, issueRowLabel, STAT_LABELS, statText } from './issueModel'

const CHART_HEIGHT = 32
const AVATAR_SIZE = 18

interface IssueListRowProps {
    row: IssueRow
    window: ErrorsWindow
    /** The sorted stat's number and label draw stronger than the other two. */
    sort: IssueSort
    myName: string
    onOpen: (row: IssueRow) => void
}

export const IssueListRow = memo(function IssueListRow({
    row,
    window,
    sort,
    myName,
    onOpen,
}: IssueListRowProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={() => onOpen(row)}
            accessibilityRole="button"
            accessibilityLabel={issueRowLabel(row, window)}
            pressedBackground={colors.pressed}
            style={styles.card}
            testID={`issue-row-${row.id}`}
        >
            <View style={styles.head}>
                <Text style={[styles.title, row.badge === 'new' && styles.newTitle]} numberOfLines={1}>
                    {row.title}
                </Text>
                {row.badge ? <IssueBadgePill badge={row.badge} /> : null}
                {row.assignee.kind === 'none' ? null : (
                    <View style={styles.assignee}>
                        <AssigneeAvatar assignee={row.assignee} myName={myName} size={AVATAR_SIZE} />
                    </View>
                )}
            </View>
            {/* A missing message keeps its line, so every card is as tall as the loading card. */}
            <Text style={styles.detail} numberOfLines={1}>
                {row.detail ?? 'No message'}
            </Text>
            <View style={styles.chart}>
                <SparkBars
                    values={row.volume}
                    height={CHART_HEIGHT}
                    color={colors.disabled}
                    highlightColor={colors.orange}
                    highlightFrom={highlightStart(row.volume, row.badge)}
                />
            </View>
            <View style={styles.stats}>
                {ISSUE_STATS.map((stat) => {
                    const sorted = stat === sort
                    const none = stat === 'sessions' && row.sessions <= 0
                    return (
                        <View key={stat} style={styles.stat}>
                            <Text
                                style={[styles.value, sorted && styles.valueSorted, none && styles.valueNone]}
                                numberOfLines={1}
                                adjustsFontSizeToFit
                            >
                                {statText(stat, row[stat])}
                            </Text>
                            <View style={styles.labelLine}>
                                {/* Ties the bars above to this number, as a chart legend does. */}
                                {stat === 'occurrences' ? <View style={styles.swatch} /> : null}
                                <Text
                                    style={[styles.label, sorted && styles.labelSorted]}
                                    numberOfLines={1}
                                    adjustsFontSizeToFit
                                >
                                    {STAT_LABELS[stat]}
                                </Text>
                            </View>
                        </View>
                    )
                })}
            </View>
        </Pressable44>
    )
})

/** The loading card: the loaded card's frame and line boxes, so nothing moves when the issues arrive. */
export function IssueListRowSkeleton(): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.card}>
            <View style={styles.head}>
                <View style={[styles.block, styles.blockTitle]} />
            </View>
            <View style={styles.skeletonDetail}>
                <View style={[styles.block, styles.blockDetail]} />
            </View>
            <View style={styles.chart}>
                <View style={[styles.block, styles.blockChart]} />
            </View>
            <View style={styles.stats}>
                {ISSUE_STATS.map((stat) => (
                    <View key={stat} style={styles.stat}>
                        <View style={styles.skeletonValue}>
                            <View style={[styles.block, styles.blockValue]} />
                        </View>
                        <View style={styles.skeletonLabel}>
                            <View style={[styles.block, styles.blockLabel]} />
                        </View>
                    </View>
                ))}
            </View>
        </View>
    )
}

const DETAIL_LINE = type.meta.lineHeight
const VALUE_LINE = 21
const LABEL_LINE = 16

const useStyles = createStyles(({ colors }) => ({
    card: {
        paddingTop: 12,
        paddingHorizontal: 14,
        paddingBottom: 6,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    head: {
        minHeight: 22,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    title: {
        ...type.rowTitle,
        color: colors.ink,
        flexShrink: 1,
    },
    newTitle: {
        fontWeight: '700',
    },
    assignee: {
        marginLeft: 'auto',
        paddingLeft: 4,
    },
    detail: {
        ...type.meta,
        marginTop: 1,
        color: colors.secondary,
    },
    chart: {
        marginTop: 8,
    },
    stats: {
        marginTop: 6,
        flexDirection: 'row',
        gap: 20,
    },
    stat: {
        flex: 1,
        minWidth: 0,
        paddingVertical: 4,
    },
    value: {
        fontSize: 17,
        lineHeight: VALUE_LINE,
        fontWeight: '600',
        fontVariant: ['tabular-nums'],
        color: colors.ink,
    },
    valueSorted: {
        fontWeight: '700',
    },
    valueNone: {
        color: colors.secondary,
    },
    labelLine: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
    },
    label: {
        fontSize: 13,
        lineHeight: LABEL_LINE,
        color: colors.secondary,
        flexShrink: 1,
    },
    labelSorted: {
        color: colors.ink,
    },
    swatch: {
        width: 10,
        height: 10,
        borderRadius: 3,
        backgroundColor: colors.disabled,
    },
    block: {
        backgroundColor: colors.sunken,
        borderRadius: 4,
    },
    blockTitle: {
        width: '42%',
        height: 14,
    },
    skeletonDetail: {
        marginTop: 1,
        height: DETAIL_LINE,
        justifyContent: 'center',
    },
    blockDetail: {
        width: '72%',
        height: 11,
    },
    blockChart: {
        height: CHART_HEIGHT,
        borderRadius: radii.markSmall,
    },
    skeletonValue: {
        height: VALUE_LINE,
        justifyContent: 'center',
    },
    blockValue: {
        width: 44,
        height: 15,
    },
    skeletonLabel: {
        height: LABEL_LINE,
        justifyContent: 'center',
    },
    blockLabel: {
        width: 60,
        maxWidth: '100%',
        height: 11,
    },
}))
