import { Fragment, type ReactElement, type ReactNode } from 'react'
import type { LayoutChangeEvent } from 'react-native'
import { Text, View } from 'react-native'

import type { ErrorsWindow, IssueReleaseApi } from '@/api/errorTracking'
import { Sparkline } from '@/ui/chart/Sparkline'
import { Eyebrow } from '@/ui/Eyebrow'
import { IconTile } from '@/ui/IconTile'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { ClockIcon } from '@/ui/icons/ClockIcon'
import { GitBranchIcon } from '@/ui/icons/GitBranchIcon'
import { InboxIcon } from '@/ui/icons/InboxIcon'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { createStyles, useColors } from '@/ui/theme'
import { fonts, iconSizes, lineHeight, radii, type } from '@/ui/tokens'

import { AssigneeAvatar } from './AssigneeAvatar'
import { IssueBadgePill, StatusChip } from './IssueBadges'
import {
    agoPhrase,
    type BreakdownRow,
    type IssueAssignee,
    type IssueBadge,
    type IssueFrame,
    type SessionSample,
    type TrendCaption,
} from './issueModel'

const WINDOWS: readonly ErrorsWindow[] = ['24h', '7d']
const WINDOW_SHORT: Record<ErrorsWindow, string> = { '24h': 'last 24h', '7d': 'last 7d' }
const CHART_LABEL: Record<ErrorsWindow, string> = { '24h': 'Last 24 hours', '7d': 'Last 7 days' }
const CHART_START: Record<ErrorsWindow, string> = { '24h': '24h ago', '7d': '7d ago' }

export function Section({
    title,
    trailing,
    children,
}: {
    title: string
    trailing?: ReactNode
    children: ReactNode
}): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.section}>
            <View style={styles.sectionHeader}>
                <Eyebrow>{title}</Eyebrow>
                {trailing}
            </View>
            {children}
        </View>
    )
}

interface IssueHeaderProps {
    onTitleLayout?: (event: LayoutChangeEvent) => void
    eyebrow: string
    status: string
    badge: IssueBadge | null
    name: string
    description: string | null
    firstSeen: string | null
    lastSeen: string | null
    now: Date
    assignee: IssueAssignee
    myName: string
    onAssign: () => void
}

export function IssueHeader({
    onTitleLayout,
    eyebrow,
    status,
    badge,
    name,
    description,
    firstSeen,
    lastSeen,
    now,
    assignee,
    myName,
    onAssign,
}: IssueHeaderProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const seen = [
        firstSeen ? `First seen ${agoPhrase(firstSeen, now)}` : null,
        lastSeen ? `last seen ${agoPhrase(lastSeen, now)}` : null,
    ].filter(Boolean)
    return (
        <View>
            <View onLayout={onTitleLayout}>
                <View style={styles.eyebrowRow}>
                    <Eyebrow>{eyebrow}</Eyebrow>
                    <StatusChip status={status} />
                    {badge ? <IssueBadgePill badge={badge} /> : null}
                </View>
                <Text style={styles.headline} accessibilityRole="header" numberOfLines={5} testID="issue-title">
                    <Text style={styles.headlineType}>{name}</Text>
                    {description ? ` ${description}` : ''}
                </Text>
            </View>
            {seen.length > 0 ? (
                <View style={styles.byline}>
                    <ClockIcon size={iconSizes.inline} color={colors.tertiary} />
                    <Text style={styles.bylineText} numberOfLines={1}>
                        {seen.join(' · ')}
                    </Text>
                </View>
            ) : null}
            <View style={styles.chips}>
                <AssigneeChip assignee={assignee} myName={myName} onPress={onAssign} />
            </View>
        </View>
    )
}

function assigneeLabel(assignee: IssueAssignee, myName: string): string {
    switch (assignee.kind) {
        case 'me':
            return myName || 'You'
        case 'user':
            return 'A teammate'
        case 'role':
            return 'A role'
        default:
            return 'Assign'
    }
}

/** The same chip as the report's owner chip: a dashed orange circle and "Assign" while nobody owns it. */
function AssigneeChip({
    assignee,
    myName,
    onPress,
}: {
    assignee: IssueAssignee
    myName: string
    onPress: () => void
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const label = assigneeLabel(assignee, myName)
    const none = assignee.kind === 'none'
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="button"
            accessibilityLabel={none ? 'No owner, assign' : `Owner: ${label}, change`}
            pressedBackground={colors.pressed}
            style={styles.chip}
            testID="issue-assignee-chip"
        >
            {none ? (
                <View style={styles.unassigned} />
            ) : (
                <AssigneeAvatar assignee={assignee} myName={myName} size={18} />
            )}
            <Text numberOfLines={1} style={[styles.chipLabel, none && styles.alert]}>
                {label}
            </Text>
            <ChevronDownIcon size={iconSizes.small} color={colors.tertiary} />
        </Pressable44>
    )
}

interface ImpactSectionProps {
    window: ErrorsWindow
    onWindow: (window: ErrorsWindow) => void
    loading: boolean
    users: number | null
    sessions: number | null
    occurrences: number | null
    volume: readonly number[]
    highlightFrom: number | null
    caption: TrendCaption | null
}

export function ImpactSection({
    window,
    onWindow,
    loading,
    users,
    sessions,
    occurrences,
    volume,
    highlightFrom,
    caption,
}: ImpactSectionProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const tiles: [string, number | null][] = [
        ['Users', users],
        ['Sessions', sessions],
        ['Occurrences', occurrences],
    ]
    return (
        <Section
            title="Impact"
            trailing={
                <SegmentedPill
                    height={34}
                    segmentWidth={46}
                    segments={WINDOWS.map((option) => ({
                        key: option,
                        accessibilityLabel: option === '24h' ? 'Last 24 hours' : 'Last 7 days',
                        accessibilityRole: 'tab',
                        selected: option === window,
                        onPress: () => onWindow(option),
                        testID: `issue-window-${option}`,
                        children: <Text style={styles.segmentText}>{option}</Text>,
                    }))}
                />
            }
        >
            <View style={styles.tiles}>
                {tiles.map(([label, value]) => (
                    <View key={label} style={styles.tile} testID={`issue-impact-${label.toLowerCase()}`}>
                        <Text style={styles.tileValue} numberOfLines={1} adjustsFontSizeToFit>
                            {value === null ? (loading ? '…' : '0') : value.toLocaleString()}
                        </Text>
                        <Text style={styles.tileLabel} numberOfLines={1}>
                            {label}
                        </Text>
                        <Text style={styles.tileWindow}>{WINDOW_SHORT[window]}</Text>
                    </View>
                ))}
            </View>
            {volume.length > 1 ? (
                <View style={styles.card} testID="issue-volume">
                    <View style={styles.cardHead}>
                        <Text style={styles.cardLabel}>{CHART_LABEL[window]}</Text>
                        {caption ? (
                            <Text style={[styles.caption, caption.rising && styles.captionRising]}>{caption.text}</Text>
                        ) : null}
                    </View>
                    <Sparkline
                        values={volume}
                        highlightFrom={highlightFrom ?? 0}
                        color={highlightFrom === null ? colors.muted : colors.orange}
                        width="100%"
                        height={72}
                    />
                    <View style={styles.axis}>
                        <Text style={styles.axisText}>{CHART_START[window]}</Text>
                        <Text style={styles.axisText}>Now</Text>
                    </View>
                </View>
            ) : null}
        </Section>
    )
}

export function ReleaseCard({
    latest,
    first,
    library,
}: {
    latest: IssueReleaseApi | undefined
    first: IssueReleaseApi | undefined
    library: string | null
}): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    if (!latest?.version && !library) {
        return null
    }
    const introduced = latest?.version && first?.version === latest.version
    return (
        <Section title="Release">
            <View style={[styles.card, styles.release]} testID="issue-release">
                <IconTile>
                    <GitBranchIcon size={iconSizes.control} color={colors.ink} />
                </IconTile>
                <View style={styles.releaseText}>
                    <View style={styles.releaseTitle}>
                        <Text style={styles.rowTitle} numberOfLines={1}>
                            {latest?.version ?? library}
                        </Text>
                        {latest?.commit_id ? <Text style={styles.commit}>{latest.commit_id.slice(0, 7)}</Text> : null}
                    </View>
                    {latest?.version ? (
                        <Text style={styles.rowSub} numberOfLines={1}>
                            {[latest.branch, library].filter(Boolean).join(' · ') || 'Latest release with this error'}
                        </Text>
                    ) : null}
                    {introduced ? <Text style={styles.releaseNote}>First seen in this release</Text> : null}
                </View>
            </View>
        </Section>
    )
}

interface FramesCardProps {
    heading: string
    frames: readonly IssueFrame[]
    total: number
    loading: boolean
    expanded: boolean
    onToggle: () => void
}

export function FramesCard({ heading, frames, total, loading, expanded, onToggle }: FramesCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const shown = expanded ? frames : frames.slice(0, 1)
    const canExpand = frames.length > 1
    const footer = loading
        ? 'Loading the stack…'
        : total === 0
          ? 'No in-app frames on the latest event'
          : expanded
            ? `${shown.length} of ${total} in-app ${total === 1 ? 'frame' : 'frames'}`
            : `In-app frame 1 of ${total}`
    return (
        <View style={styles.trace} testID="issue-frames">
            <Text style={[styles.mono, styles.traceError]} numberOfLines={4}>
                {heading}
            </Text>
            {shown.length > 0 ? (
                <View>
                    {shown.map((frame, index) => (
                        <Text
                            key={`${frame.functionName}-${frame.location}-${index}`}
                            style={[styles.mono, styles.frame]}
                        >
                            at <Text style={index === 0 ? styles.firstFn : undefined}>{frame.functionName}</Text>
                            {frame.location ? ` (${frame.location})` : ''}
                        </Text>
                    ))}
                </View>
            ) : null}
            <View style={styles.traceFooter}>
                <Text style={[styles.mono, styles.frame, styles.footerText]}>{footer}</Text>
                {canExpand ? (
                    <Pressable44
                        onPress={onToggle}
                        accessibilityRole="button"
                        accessibilityLabel={expanded ? 'Show less' : 'Show all frames'}
                        accessibilityState={{ expanded }}
                        pressedBackground={colors.darkDivider}
                        style={styles.toggle}
                        testID="issue-frames-toggle"
                    >
                        <Text style={[styles.mono, styles.firstFn]}>{expanded ? 'Show less' : 'Show all'}</Text>
                    </Pressable44>
                ) : null}
            </View>
        </View>
    )
}

export function BreakdownCard({ rows }: { rows: readonly BreakdownRow[] }): ReactElement | null {
    const colors = useColors()
    const styles = useStyles()
    if (rows.length === 0) {
        return null
    }
    const shades = [colors.ink, colors.muted, colors.disabled]
    return (
        <View style={styles.card} testID="issue-breakdown">
            {rows.map((row, rowIndex) => (
                <Fragment key={row.key}>
                    {rowIndex > 0 ? <View style={styles.cardDivider} /> : null}
                    <View
                        style={styles.breakdownRow}
                        accessible
                        accessibilityLabel={`${row.label}: ${row.values.map((v) => `${v.value} ${v.percent}%`).join(', ')}`}
                    >
                        <Text style={styles.breakdownLabel}>{row.label}</Text>
                        <View style={styles.breakdownBody}>
                            <Text style={styles.breakdownValues} numberOfLines={2}>
                                {row.values.map((value, index) => (
                                    <Text key={value.value}>
                                        {index > 0 ? '   ' : ''}
                                        <Text style={index === 0 ? styles.breakdownTop : undefined}>{value.value}</Text>
                                        <Text style={styles.breakdownPercent}> {value.percent}%</Text>
                                    </Text>
                                ))}
                            </Text>
                            <View style={styles.bar}>
                                {row.values.map((value, index) => (
                                    <View
                                        key={value.value}
                                        style={{
                                            flex: value.percent,
                                            backgroundColor: shades[index] ?? colors.disabled,
                                        }}
                                    />
                                ))}
                                <View
                                    style={{
                                        flex: Math.max(0, 100 - row.values.reduce((sum, v) => sum + v.percent, 0)),
                                    }}
                                />
                            </View>
                        </View>
                    </View>
                </Fragment>
            ))}
        </View>
    )
}

export function SessionRows({
    sessions,
    now,
    onOpen,
}: {
    sessions: readonly SessionSample[]
    now: Date
    onOpen: (session: SessionSample, position: number) => void
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.card} testID="issue-sessions">
            {sessions.map((session, index) => (
                <Fragment key={session.sessionId}>
                    {index > 0 ? <View style={styles.cardDivider} /> : null}
                    <LinkRow
                        icon={<PlayIcon size={iconSizes.inline} color={colors.ink} />}
                        title={session.platform ?? 'Session'}
                        sub={`Error ${agoPhrase(session.at, now)}`}
                        onPress={() => onOpen(session, index)}
                        testID={`issue-session-${index}`}
                    />
                </Fragment>
            ))}
        </View>
    )
}

export function ReportLinkRow({
    title,
    updatedAt,
    now,
    onOpen,
}: {
    title: string
    updatedAt: string
    now: Date
    onOpen: () => void
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <View style={styles.card}>
            <LinkRow
                icon={<InboxIcon size={iconSizes.control} color={colors.ink} />}
                title={title}
                sub={`Updated ${agoPhrase(updatedAt, now)}`}
                onPress={onOpen}
                testID="issue-report"
            />
        </View>
    )
}

function LinkRow({
    icon,
    title,
    sub,
    onPress,
    testID,
}: {
    icon: ReactNode
    title: string
    sub: string
    onPress: () => void
    testID: string
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="button"
            accessibilityLabel={`${title}, ${sub}`}
            pressedBackground={colors.pressed}
            style={styles.linkRow}
            testID={testID}
        >
            <IconTile>{icon}</IconTile>
            <View style={styles.linkText}>
                <Text style={styles.rowTitle} numberOfLines={2}>
                    {title}
                </Text>
                <Text style={styles.rowSub} numberOfLines={1}>
                    {sub}
                </Text>
            </View>
            <ChevronRightIcon size={iconSizes.small} color={colors.tertiary} />
        </Pressable44>
    )
}

const useStyles = createStyles(({ colors }) => ({
    section: {
        marginTop: 26,
        gap: 10,
    },
    sectionHeader: {
        minHeight: 34,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
        paddingHorizontal: 2,
    },
    eyebrowRow: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 8,
    },
    headline: {
        ...type.headline,
        color: colors.ink,
        marginTop: 10,
    },
    headlineType: {
        color: colors.orange,
    },
    byline: {
        marginTop: 8,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
    },
    bylineText: {
        ...type.metaSmall,
        color: colors.secondary,
        flexShrink: 1,
    },
    chips: {
        marginTop: 12,
        flexDirection: 'row',
    },
    chip: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        height: 32,
        maxWidth: '100%',
        paddingLeft: 8,
        paddingRight: 10,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    chipLabel: {
        flexShrink: 1,
        fontSize: 13,
        lineHeight: lineHeight(13, 1.3),
        fontWeight: '500',
        color: colors.ink,
    },
    alert: {
        color: colors.orange,
    },
    unassigned: {
        width: 18,
        height: 18,
        borderRadius: 9,
        borderWidth: 1.5,
        borderStyle: 'dashed',
        borderColor: colors.orange,
    },
    segmentText: {
        ...type.meta,
        fontWeight: '600',
        color: colors.ink,
    },
    tiles: {
        flexDirection: 'row',
        gap: 8,
    },
    tile: {
        flex: 1,
        minWidth: 0,
        padding: 12,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        gap: 2,
    },
    tileValue: {
        fontFamily: fonts.mono,
        fontSize: 20,
        fontWeight: '600',
        color: colors.ink,
    },
    tileLabel: {
        ...type.metaSmall,
        color: colors.ink,
    },
    tileWindow: {
        ...type.monoSmall,
        color: colors.tertiary,
    },
    card: {
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
        overflow: 'hidden',
    },
    cardHead: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: 8,
        paddingHorizontal: 14,
        paddingTop: 12,
        paddingBottom: 8,
    },
    cardLabel: {
        ...type.metaSmall,
        color: colors.secondary,
    },
    caption: {
        ...type.metaSmall,
        fontWeight: '600',
        color: colors.secondary,
    },
    captionRising: {
        color: colors.orange,
    },
    axis: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        paddingHorizontal: 14,
        paddingTop: 6,
        paddingBottom: 12,
    },
    axisText: {
        ...type.monoSmall,
        color: colors.tertiary,
    },
    cardDivider: {
        height: 1,
        backgroundColor: colors.hairline,
    },
    release: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        padding: 14,
    },
    releaseText: {
        flex: 1,
        minWidth: 0,
        gap: 2,
    },
    releaseTitle: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    commit: {
        ...type.monoSmall,
        color: colors.secondary,
        backgroundColor: colors.sunken,
        paddingHorizontal: 6,
        paddingVertical: 2,
        borderRadius: 6,
        overflow: 'hidden',
    },
    releaseNote: {
        ...type.metaSmall,
        fontWeight: '600',
        color: colors.orange,
        marginTop: 2,
    },
    rowTitle: {
        ...type.bodySmallStrong,
        color: colors.ink,
        flexShrink: 1,
    },
    rowSub: {
        ...type.meta,
        color: colors.secondary,
    },
    trace: {
        backgroundColor: colors.terminal,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.terminalBorder,
        paddingTop: 13,
        paddingHorizontal: 15,
        gap: 8,
        overflow: 'hidden',
    },
    mono: {
        ...type.mono,
    },
    traceError: {
        color: colors.orangeLight,
    },
    frame: {
        color: colors.onTerminalMuted,
    },
    firstFn: {
        color: colors.onTerminal,
    },
    traceFooter: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
        paddingTop: 2,
        borderTopWidth: 1,
        borderTopColor: colors.darkDivider,
        minHeight: 40,
    },
    footerText: {
        flexShrink: 1,
    },
    toggle: {
        height: 32,
        paddingHorizontal: 8,
        marginRight: -8,
        borderRadius: 8,
        justifyContent: 'center',
    },
    breakdownRow: {
        flexDirection: 'row',
        gap: 12,
        paddingHorizontal: 14,
        paddingVertical: 12,
    },
    breakdownLabel: {
        ...type.metaSmall,
        color: colors.secondary,
        width: 92,
    },
    breakdownBody: {
        flex: 1,
        minWidth: 0,
        gap: 8,
    },
    breakdownValues: {
        ...type.metaSmall,
        color: colors.secondary,
    },
    breakdownTop: {
        color: colors.ink,
    },
    breakdownPercent: {
        fontFamily: fonts.mono,
        fontSize: 12,
        color: colors.tertiary,
    },
    bar: {
        height: 4,
        flexDirection: 'row',
        borderRadius: 2,
        overflow: 'hidden',
        backgroundColor: colors.sunken,
    },
    linkRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 14,
        paddingHorizontal: 14,
        paddingVertical: 12,
    },
    linkText: {
        flex: 1,
        minWidth: 0,
        gap: 2,
    },
}))
