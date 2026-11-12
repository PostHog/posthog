import { Fragment, type ReactElement, type ReactNode } from 'react'
import { Text, View } from 'react-native'

import { ArrowDownIcon } from '@/ui/icons/ArrowDownIcon'
import { ArrowUpIcon } from '@/ui/icons/ArrowUpIcon'
import { CheckCircleIcon } from '@/ui/icons/CheckCircleIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { fonts, radii, type } from '@/ui/tokens'

import type { AboutWhat } from './aboutCopy'
import { VariantSwatch } from './DetailSection'
import {
    type CellModel,
    formatChance,
    formatCount,
    formatDelta,
    formatMetricValue,
    formatPValue,
    type MetricCardModel,
    type StatsSettings,
} from './detailModel'
import { IntervalBar } from './IntervalBar'

interface MetricCardProps {
    card: MetricCardModel
    settings: StatsSettings
    /** Every cell and column label opens "About this number". */
    onExplain: (what: AboutWhat, variantKey: string) => void
    testID?: string
}

const EMPTY_COPY: Record<Exclude<MetricCardModel['state'], 'ready'>, string> = {
    none: 'No results yet. They show here after the first calculation.',
    pending: 'Calculating this metric…',
    failed: "This metric couldn't be calculated in the last run. Open the experiment on the web to see why.",
    not_enough: 'Not enough data yet. Results show once each variant has enough people in this metric.',
}

/** One card per metric, the baseline first. Value, change and chance to win (or p-value) fit a phone's width. */
export function MetricCard({ card, settings, onExplain, testID }: MetricCardProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const { def } = card
    const freq = settings.method === 'freq'
    const decrease = def.goal === 'decrease'
    const leader = card.leaderKey ?? card.variants[0]?.key ?? null
    const head = (
        <View style={styles.head}>
            <Text style={styles.name} numberOfLines={3}>
                {def.name}
            </Text>
            <View style={styles.goal}>
                {decrease ? (
                    <ArrowDownIcon size={13} color={colors.secondary} />
                ) : (
                    <ArrowUpIcon size={13} color={colors.secondary} />
                )}
                <Text style={styles.goalText}>{decrease ? 'Lower is better' : 'Higher is better'}</Text>
            </View>
        </View>
    )
    if (card.state !== 'ready' || !card.baseline) {
        return (
            <View style={styles.card} testID={testID}>
                {head}
                <Text style={styles.empty}>{EMPTY_COPY[card.state === 'ready' ? 'none' : card.state]}</Text>
            </View>
        )
    }
    const baseline = card.baseline
    const column = (what: AboutWhat, label: string, flex: number): ReactElement => (
        <Pressable44
            onPress={() => (leader ? onExplain(what, leader) : undefined)}
            disabled={!leader}
            accessibilityRole="button"
            accessibilityLabel={`About ${label.toLowerCase()}`}
            pressedBackground={colors.pressed}
            style={[styles.column, { flex }]}
            testID={testID ? `${testID}-column-${what}` : undefined}
        >
            <Text style={styles.columnText}>{label}</Text>
        </Pressable44>
    )
    return (
        <View style={styles.card} testID={testID}>
            {head}
            <View style={styles.columns}>
                {column('value', 'Value', 1)}
                {column('delta', 'Change', 1.35)}
                {column(freq ? 'p_value' : 'chance', freq ? 'p-value' : 'Chance to win', 1.1)}
            </View>
            <VariantBlock cell={baseline} baselineKey={baseline.key}>
                <ValueCell
                    card={card}
                    cell={baseline}
                    onPress={() => onExplain('control', baseline.key)}
                    testID={testID}
                />
                <Text style={styles.baselineNote}>Baseline for the other variants</Text>
            </VariantBlock>
            {card.variants.map((cell) => (
                <Fragment key={cell.key}>
                    <View style={styles.divider} />
                    <VariantBlock cell={cell} baselineKey={baseline.key}>
                        <ValueCell
                            card={card}
                            cell={cell}
                            onPress={() => onExplain('value', cell.key)}
                            testID={testID}
                        />
                        <DeltaCell
                            card={card}
                            cell={cell}
                            onPress={() => onExplain('delta', cell.key)}
                            testID={testID}
                        />
                        <StatCell
                            cell={cell}
                            freq={freq}
                            onPress={() => onExplain(freq ? 'p_value' : 'chance', cell.key)}
                            testID={testID}
                        />
                    </VariantBlock>
                </Fragment>
            ))}
        </View>
    )
}

function VariantBlock({
    cell,
    baselineKey,
    children,
}: {
    cell: CellModel
    baselineKey: string
    children: ReactNode
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const bad = cell.better === false
    return (
        <View style={styles.block}>
            <View style={styles.variantRow}>
                <View style={styles.variantKey}>
                    <VariantSwatch colorIndex={cell.colorIndex} />
                    <Text style={styles.keyText} numberOfLines={1}>
                        {cell.key}
                    </Text>
                    {cell.key === baselineKey ? <Text style={styles.baselineTag}>baseline</Text> : null}
                </View>
                {cell.significant ? (
                    <View style={styles.significant} testID={`experiment-significant-${cell.key}`}>
                        {bad ? (
                            <ArrowDownIcon size={14} color={colors.diffRed} />
                        ) : (
                            <CheckCircleIcon size={14} color={colors.diffGreen} />
                        )}
                        <Text style={[styles.significantText, bad ? styles.bad : styles.good]}>Significant</Text>
                    </View>
                ) : null}
            </View>
            <View style={styles.cells}>{children}</View>
        </View>
    )
}

function Cell({
    flex,
    onPress,
    label,
    children,
    testID,
}: {
    flex: number
    onPress: () => void
    label: string
    children: ReactNode
    testID?: string
}): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="button"
            accessibilityLabel={label}
            accessibilityHint="Explains this number"
            pressedBackground={colors.pressed}
            style={[styles.cell, { flex }]}
            testID={testID}
        >
            {children}
        </Pressable44>
    )
}

function ValueCell({
    card,
    cell,
    onPress,
    testID,
}: {
    card: MetricCardModel
    cell: CellModel
    onPress: () => void
    testID?: string
}): ReactElement {
    const styles = useStyles()
    const value = formatMetricValue(card.def.kind, cell.value)
    const sub =
        card.def.kind === 'rate' && cell.numerator !== null
            ? `${formatCount(cell.numerator)} / ${formatCount(cell.samples)}`
            : `${formatCount(cell.samples)} people`
    return (
        <Cell
            flex={1}
            onPress={onPress}
            label={`${cell.key} value ${value}, ${sub}`}
            testID={testID ? `${testID}-value-${cell.key}` : undefined}
        >
            <Text style={styles.cellValue} numberOfLines={1} adjustsFontSizeToFit>
                {value}
            </Text>
            <Text style={styles.cellSub} numberOfLines={1}>
                {sub}
            </Text>
        </Cell>
    )
}

function DeltaCell({
    card,
    cell,
    onPress,
    testID,
}: {
    card: MetricCardModel
    cell: CellModel
    onPress: () => void
    testID?: string
}): ReactElement {
    const styles = useStyles()
    const delta = cell.delta === null ? '—' : formatDelta(cell.delta, card.unit)
    const toneStyle = cell.significant ? (cell.better ? styles.good : styles.bad) : null
    return (
        <Cell
            flex={1.35}
            onPress={onPress}
            label={
                cell.interval
                    ? `${cell.key} change ${delta}, range ${formatDelta(cell.interval[0], card.unit)} to ${formatDelta(cell.interval[1], card.unit)}`
                    : `${cell.key} change ${delta}`
            }
            testID={testID ? `${testID}-delta-${cell.key}` : undefined}
        >
            <Text style={[styles.cellValue, toneStyle]} numberOfLines={1} adjustsFontSizeToFit>
                {delta}
            </Text>
            {cell.interval && cell.delta !== null ? (
                <IntervalBar
                    interval={cell.interval}
                    delta={cell.delta}
                    unit={card.unit}
                    scale={card.scale}
                    side={cell.side}
                />
            ) : null}
        </Cell>
    )
}

function StatCell({
    cell,
    freq,
    onPress,
    testID,
}: {
    cell: CellModel
    freq: boolean
    onPress: () => void
    testID?: string
}): ReactElement {
    const styles = useStyles()
    const value = freq
        ? cell.pValue === null
            ? '—'
            : formatPValue(cell.pValue)
        : cell.chanceToWin === null
          ? '—'
          : formatChance(cell.chanceToWin)
    return (
        <Cell
            flex={1.1}
            onPress={onPress}
            label={freq ? `${cell.key} p-value ${value}` : `${cell.key} chance to win ${value}`}
            testID={testID ? `${testID}-${freq ? 'p' : 'chance'}-${cell.key}` : undefined}
        >
            <Text style={styles.cellValue} numberOfLines={1} adjustsFontSizeToFit>
                {value}
            </Text>
            <Text style={styles.cellSub} numberOfLines={1}>
                {freq ? 'p-value' : 'to win'}
            </Text>
        </Cell>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        paddingHorizontal: 12,
        paddingTop: 14,
        paddingBottom: 12,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.hairline,
        backgroundColor: colors.surface,
    },
    head: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 10,
        paddingHorizontal: 2,
    },
    name: {
        ...type.bodyStrong,
        color: colors.ink,
        flex: 1,
    },
    goal: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 3,
        paddingTop: 3,
    },
    goalText: {
        ...type.meta,
        color: colors.secondary,
    },
    empty: {
        ...type.metaSmall,
        color: colors.secondary,
        paddingHorizontal: 2,
        paddingTop: 10,
        paddingBottom: 4,
    },
    columns: {
        flexDirection: 'row',
        gap: 8,
        marginTop: 10,
        paddingBottom: 6,
        borderBottomWidth: 1,
        borderBottomColor: colors.hairline,
    },
    column: {
        minWidth: 0,
        minHeight: 32,
        justifyContent: 'center',
        paddingHorizontal: 4,
        borderRadius: 8,
    },
    columnText: {
        ...type.meta,
        fontWeight: '500',
        color: colors.secondary,
        textDecorationLine: 'underline',
        textDecorationStyle: 'dotted',
    },
    block: {
        paddingTop: 12,
        paddingBottom: 4,
        gap: 8,
    },
    variantRow: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 8,
        paddingHorizontal: 2,
    },
    variantKey: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        flexShrink: 1,
    },
    keyText: {
        fontFamily: fonts.mono,
        fontSize: 14,
        color: colors.ink,
        flexShrink: 1,
    },
    baselineTag: {
        ...type.meta,
        color: colors.tertiary,
    },
    significant: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
    },
    significantText: {
        ...type.meta,
        fontWeight: '600',
    },
    good: {
        color: colors.diffGreen,
    },
    bad: {
        color: colors.diffRed,
    },
    cells: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    cell: {
        minWidth: 0,
        minHeight: 56,
        paddingHorizontal: 10,
        paddingVertical: 8,
        borderRadius: 10,
        backgroundColor: colors.sunken,
        justifyContent: 'center',
        gap: 4,
    },
    cellValue: {
        fontFamily: fonts.mono,
        fontSize: 15,
        fontWeight: '600',
        color: colors.ink,
    },
    cellSub: {
        ...type.meta,
        fontSize: 12,
        color: colors.tertiary,
    },
    baselineNote: {
        ...type.meta,
        color: colors.tertiary,
        flex: 2.45,
        paddingLeft: 4,
    },
    divider: {
        height: 1,
        backgroundColor: colors.hairline,
        marginTop: 8,
    },
}))
