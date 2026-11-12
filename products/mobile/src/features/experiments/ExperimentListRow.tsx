import { Fragment, memo, type ReactElement } from 'react'
import { Text, View } from 'react-native'

import { Dot } from '@/ui/Dot'
import { ArrowDownIcon } from '@/ui/icons/ArrowDownIcon'
import { CheckCircleIcon } from '@/ui/icons/CheckCircleIcon'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, type ThemeColors, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import type { ExperimentConclusion, ExperimentRow } from './experimentModel'
import { BADGE_LABELS, type RowBadge, type RowLine, rowBadge, rowLine, rowLineText, rowMeta } from './listCopy'

interface ExperimentListRowProps {
    row: ExperimentRow
    now: number
    /** The viewer's user UUID, so a draft they created says "by you". */
    myUuid: string | null
    onOpen: (row: ExperimentRow) => void
    /** Drafts only: opens the launch confirmation. */
    onLaunch?: (row: ExperimentRow) => void
}

/** The web's conclusion colors: green won, red lost, amber inconclusive, gray otherwise. */
export function conclusionColor(conclusion: ExperimentConclusion | null, colors: ThemeColors): string {
    switch (conclusion) {
        case 'won':
            return colors.diffGreen
        case 'lost':
            return colors.diffRed
        case 'inconclusive':
            return colors.yellow
        default:
            return colors.tertiary
    }
}

function badgeColors(badge: RowBadge, colors: ThemeColors): { text: string; border: string } {
    switch (badge) {
        case 'ship':
            return { text: colors.diffGreen, border: colors.diffGreenBorder }
        case 'losing':
            return { text: colors.diffRed, border: colors.diffRed }
        case 'new':
            return { text: colors.blue, border: colors.blueLight }
        default:
            return { text: colors.secondary, border: colors.border }
    }
}

function LineView({ row, line }: { row: ExperimentRow; line: RowLine }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const leadColor =
        line.tone === 'good'
            ? colors.diffGreen
            : line.tone === 'bad'
              ? colors.diffRed
              : row.status === 'complete'
                ? colors.ink
                : colors.secondary
    let mark: ReactElement | null = null
    if (line.tone === 'good') {
        mark = <CheckCircleIcon size={16} color={colors.diffGreen} strokeWidth={2.2} />
    } else if (line.tone === 'bad') {
        mark = <ArrowDownIcon size={16} color={colors.diffRed} strokeWidth={2.4} />
    } else if (line.tone === 'pending') {
        mark = <Dot color={colors.blueLight} size={8} />
    } else if (row.status === 'complete') {
        mark = <Dot color={conclusionColor(row.conclusion, colors)} size={8} />
    }
    const quiet = line.tone === 'quiet' || line.tone === 'pending'
    return (
        <View style={styles.line}>
            {mark}
            <Text style={[styles.lineText, quiet && styles.quiet]} numberOfLines={1}>
                {line.lead ? <Text style={[styles.lead, { color: leadColor }]}>{line.lead}</Text> : null}
                {line.parts.map((part, index) => (
                    <Fragment key={`${index}-${part.text}`}>
                        {index === 0 && !line.lead ? '' : part.glue ? ' ' : ' · '}
                        <Text style={part.strong ? styles.strong : undefined}>{part.text}</Text>
                    </Fragment>
                ))}
            </Text>
        </View>
    )
}

/** A list row: name and badge, the headline result, then the meta line. The whole row opens the experiment. */
export const ExperimentListRow = memo(function ExperimentListRow({
    row,
    now,
    myUuid,
    onOpen,
    onLaunch,
}: ExperimentListRowProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const badge = rowBadge(row)
    const line = rowLine(row, now)
    const meta = rowMeta(row, now, myUuid)
    const changed = row.changed && row.status !== 'complete' && row.status !== 'draft'
    const badgeTone = badge ? badgeColors(badge, colors) : null
    const launchable = row.status === 'draft' && onLaunch !== undefined
    return (
        <View style={styles.wrap}>
            <Pressable44
                onPress={() => onOpen(row)}
                accessibilityRole="button"
                accessibilityLabel={[
                    row.name,
                    changed ? 'Changed since your last look' : null,
                    badge ? BADGE_LABELS[badge] : null,
                    line === 'loading' ? 'Loading results' : rowLineText(line),
                    meta,
                ]
                    .filter(Boolean)
                    .join(', ')}
                pressedBackground={colors.pressed}
                style={styles.row}
                testID={`experiment-row-${row.id}`}
            >
                <View style={styles.titleLine}>
                    {changed ? <Dot color={colors.blue} size={8} /> : null}
                    <Text style={[styles.title, changed && styles.titleChanged]} numberOfLines={1}>
                        {row.name}
                    </Text>
                    {badge && badgeTone ? (
                        <View
                            style={[styles.badge, { borderColor: badgeTone.border }]}
                            testID={`experiment-badge-${badge}`}
                        >
                            <Text style={[styles.badgeText, { color: badgeTone.text }]}>{BADGE_LABELS[badge]}</Text>
                        </View>
                    ) : null}
                </View>
                {line === 'loading' ? (
                    <View style={styles.lineSkeleton} testID={`experiment-row-loading-${row.id}`} />
                ) : (
                    <LineView row={row} line={line} />
                )}
                <Text style={styles.meta} numberOfLines={1}>
                    {meta}
                </Text>
            </Pressable44>
            {launchable ? (
                <Pressable44
                    onPress={() => onLaunch(row)}
                    accessibilityRole="button"
                    accessibilityLabel={`Launch ${row.name}`}
                    pressedBackground={colors.pressed}
                    style={styles.launch}
                    haptic="selection"
                    testID={`experiment-launch-${row.id}`}
                >
                    <PlayIcon size={14} color={colors.ink} />
                    <Text style={styles.launchText}>Launch</Text>
                </Pressable44>
            ) : null}
        </View>
    )
})

const useStyles = createStyles(({ colors }) => ({
    wrap: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 10,
        borderBottomWidth: 1,
        borderBottomColor: colors.rowDivider,
    },
    row: {
        flex: 1,
        minWidth: 0,
        paddingVertical: 13,
        paddingHorizontal: 2,
        gap: 3,
    },
    titleLine: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    title: {
        ...type.rowTitle,
        fontWeight: '500',
        color: colors.ink,
        flexShrink: 1,
    },
    titleChanged: {
        fontWeight: '700',
    },
    badge: {
        height: 22,
        paddingHorizontal: 8,
        borderRadius: radii.pill,
        borderWidth: 1,
        justifyContent: 'center',
    },
    badgeText: {
        fontSize: 12,
        fontWeight: '600',
    },
    line: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        minHeight: 20,
    },
    lineText: {
        ...type.metaSmall,
        color: colors.ink,
        flexShrink: 1,
    },
    quiet: {
        color: colors.secondary,
    },
    lead: {
        fontWeight: '600',
    },
    strong: {
        fontWeight: '700',
    },
    lineSkeleton: {
        height: 14,
        width: '62%',
        marginVertical: 3,
        borderRadius: 6,
        backgroundColor: colors.sunken,
    },
    meta: {
        ...type.meta,
        color: colors.tertiary,
    },
    launch: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        height: 40,
        paddingHorizontal: 16,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    launchText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
}))
