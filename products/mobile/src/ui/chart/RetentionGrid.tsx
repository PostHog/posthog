import { type ReactElement, useCallback, useState } from 'react'
import { ScrollView, Text, View } from 'react-native'

import { formatMonthDay, parseBucketStart } from '@/lib/dates'
import { groupThousands, plural } from '@/model/adapters/text'
import type { RetentionCohortView, RetentionPeriodUnit, RetentionView } from '@/model/views'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { lineHeight, type } from '@/ui/tokens'

import { useItemChartAccessibility } from './accessibility/useChartAccessibility'
import { formatAxisDate, formatClockTime } from './chartMath'
import { seriesColor } from './palette'
import { useItemSelection } from './selection/useItemSelection'
import type { ChartAccessibilityAction, ChartTrackingContext } from './types'

/** Periods a grid in a card shows. Full screen shows all of them. */
export const INLINE_RETENTION_PERIODS = 8

const COHORT_WIDTH = 96
const CELL_WIDTH = 54
const CELL_HEIGHT = 34
const CELL_GAP = 2

interface RetentionGridProps {
    retention: RetentionView
    /** The insight's name, for the spoken summary. */
    label: string
    /** Defaults to `INLINE_RETENTION_PERIODS`. */
    maxPeriods?: number
    selectionId?: string
    trackingContext?: ChartTrackingContext
    accessibilityActions?: readonly ChartAccessibilityAction[]
    testID?: string
}

/** The cohort's start in the project's wall-clock time, such as "Sep 13" or "Sep 2026". */
export function cohortLabel(date: string, period: RetentionPeriodUnit): string {
    if (period === 'hour') {
        const at = parseBucketStart(date.slice(0, 16).replace('T', ' '))
        return `${formatMonthDay(new Date(at))}, ${formatClockTime(at)}`
    }
    return formatAxisDate(parseBucketStart(date.slice(0, 10)), period)
}

function percentText(percent: number): string {
    return `${groupThousands(percent, percent < 10 && percent > 0 ? 1 : 0)}%`
}

function channel(hex: string, offset: number): number {
    return Number.parseInt(hex.slice(offset, offset + 2), 16)
}

// In the light scheme, white text reads better than ink only on the darkest shades of the series blue. In the dark
// scheme ink is already light and reads on every shade.
const LIGHT_TEXT_FROM = 0.75

/**
 * The web's cell shade: the series color (`#RRGGBB`) mixed into the card color (`#RRGGBB`), from 12% for nobody to 90%
 * for everybody.
 */
function cellShade(percent: number, base: string, card: string): { background: string; mix: number } {
    const mix = (12 + Math.max(0, Math.min(100, percent)) * 0.78) / 100
    const blend = (offset: number): number =>
        Math.round(channel(card, offset) + (channel(base, offset) - channel(card, offset)) * mix)
    return { background: `rgb(${blend(1)}, ${blend(3)}, ${blend(5)})`, mix }
}

function cohortSentence(cohort: RetentionCohortView, labels: readonly string[], period: RetentionPeriodUnit): string {
    const cells = cohort.cells
        .slice(1)
        .map((cell, index) => `${labels[index + 1] ?? `Period ${index + 1}`} ${percentText(cell.percent)}`)
    const head = `${cohortLabel(cohort.date, period)} cohort, ${plural(cohort.size, 'person', 'people')}`
    return cells.length > 0 ? `${head}. ${cells.join(', ')}.` : `${head}.`
}

/** The mean percent of the first period after period 0, over the cohorts that reached it. */
function firstReturnMean(retention: RetentionView): number | null {
    const values = retention.cohorts.flatMap((cohort) => (cohort.cells[1] ? [cohort.cells[1].percent] : []))
    return values.length > 0 ? values.reduce((total, value) => total + value, 0) / values.length : null
}

interface SelectedCell {
    cohort: number
    period: number
}

/**
 * Retention as the web's table: one row per cohort, one column per period, shaded by the percent that came back. The
 * cohort column stays put while the periods scroll sideways. A tap on a cell shows its count under the grid.
 */
export function RetentionGrid({
    retention,
    label,
    maxPeriods = INLINE_RETENTION_PERIODS,
    selectionId,
    trackingContext,
    accessibilityActions,
    testID,
}: RetentionGridProps): ReactElement {
    const { colors, chartPalette, scheme } = useTheme()
    const styles = useStyles()
    const base = seriesColor(0, chartPalette)
    const { cohorts, period, periodLabels } = retention
    const columns = periodLabels.slice(0, maxPeriods)
    const selection = useItemSelection({
        selectionId,
        kind: 'retention',
        seriesCount: 1,
        dataKey: retention,
        trackingContext,
    })
    // The period of the tapped cell. VoiceOver selects a whole cohort, so it leaves the period unset.
    const [selectedPeriod, setSelectedPeriod] = useState<number | null>(null)
    const describe = useCallback(
        (index: number) => {
            const cohort = cohorts[index]
            return cohort ? cohortSentence(cohort, periodLabels, period) : ''
        },
        [cohorts, periodLabels, period]
    )
    const mean = firstReturnMean(retention)
    const a11y = useItemChartAccessibility({
        summary: [
            `${label}, retention table with ${plural(cohorts.length, 'cohort')}`,
            mean !== null && periodLabels[1] ? `On average ${percentText(mean)} came back in ${periodLabels[1]}` : null,
        ]
            .filter(Boolean)
            .join('. '),
        count: cohorts.length,
        selected: selection.selected,
        describe,
        select: (index) => {
            setSelectedPeriod(null)
            selection.select(index, 'accessibility')
        },
        clear: () => selection.clear('back'),
        hint: 'Swipe up or down to move between cohorts.',
        actions: accessibilityActions,
    })

    if (cohorts.length === 0) {
        return (
            <Text style={styles.empty} testID={testID}>
                No cohorts in this date range.
            </Text>
        )
    }

    const pressCell = (cohort: number, cellPeriod: number): void => {
        if (selection.selected === cohort && selectedPeriod === cellPeriod) {
            selection.clear('tap_again')
            return
        }
        setSelectedPeriod(cellPeriod)
        if (selection.selected === cohort) {
            return
        }
        selection.select(cohort, 'tap')
    }
    const picked: SelectedCell | null =
        selection.selected >= 0 && selectedPeriod !== null
            ? { cohort: selection.selected, period: selectedPeriod }
            : null
    const pickedCohort = picked ? cohorts[picked.cohort] : undefined
    const pickedCell = picked ? pickedCohort?.cells[picked.period] : undefined

    return (
        <View ref={selection.viewRef} onTouchStart={selection.onTouchStart} testID={testID} {...a11y}>
            <View style={styles.grid}>
                <View style={styles.cohorts}>
                    <Text style={styles.head}>Cohort</Text>
                    {cohorts.map((cohort, index) => (
                        <View key={cohort.key} style={styles.cohort}>
                            <Text
                                style={[styles.cohortDate, selection.selected === index && styles.cohortSelected]}
                                numberOfLines={1}
                            >
                                {cohortLabel(cohort.date, period)}
                            </Text>
                            <Text style={styles.cohortSize} numberOfLines={1}>
                                {plural(cohort.size, 'person', 'people')}
                            </Text>
                        </View>
                    ))}
                </View>
                <ScrollView
                    horizontal
                    showsHorizontalScrollIndicator={false}
                    style={styles.periods}
                    testID={testID ? `${testID}-scroll` : undefined}
                >
                    <View>
                        <View style={styles.headRow}>
                            {columns.map((column) => (
                                <Text key={column} style={[styles.head, styles.headCell]} numberOfLines={1}>
                                    {column}
                                </Text>
                            ))}
                        </View>
                        {cohorts.map((cohort, row) => (
                            <View key={cohort.key} style={styles.cellRow}>
                                {columns.map((column, index) => {
                                    const cell = cohort.cells[index]
                                    if (!cell) {
                                        return <View key={column} style={styles.cell} />
                                    }
                                    const shade = cellShade(cell.percent, base, colors.surface)
                                    const lightText = scheme === 'light' && shade.mix > LIGHT_TEXT_FROM
                                    const active = picked?.cohort === row && picked.period === index
                                    return (
                                        <Pressable44
                                            key={column}
                                            onPress={() => pressCell(row, index)}
                                            hitSlop={0}
                                            accessible={false}
                                            style={[
                                                styles.cell,
                                                { backgroundColor: shade.background },
                                                active && styles.cellActive,
                                            ]}
                                            testID={testID ? `${testID}-cell-${row}-${index}` : undefined}
                                        >
                                            <Text style={[styles.cellText, lightText && styles.cellTextLight]}>
                                                {percentText(cell.percent)}
                                            </Text>
                                        </Pressable44>
                                    )
                                })}
                            </View>
                        ))}
                    </View>
                </ScrollView>
            </View>
            {pickedCohort && pickedCell && picked ? (
                <Text style={styles.callout} testID={testID ? `${testID}-callout` : undefined}>
                    {cohortLabel(pickedCohort.date, period)} cohort, {columns[picked.period]}:{' '}
                    {percentText(pickedCell.percent)}, {groupThousands(pickedCell.count)} of{' '}
                    {plural(
                        retention.reference === 'previous' && picked.period > 0
                            ? (pickedCohort.cells[picked.period - 1]?.count ?? 0)
                            : pickedCohort.size,
                        'person',
                        'people'
                    )}
                </Text>
            ) : periodLabels.length > columns.length ? (
                <Text style={styles.callout}>
                    Showing {columns.length} of {periodLabels.length} periods. Open full screen to see all.
                </Text>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    grid: {
        flexDirection: 'row',
    },
    cohorts: {
        width: COHORT_WIDTH,
        paddingRight: 6,
    },
    cohort: {
        height: CELL_HEIGHT + CELL_GAP,
        justifyContent: 'center',
    },
    cohortDate: {
        fontSize: 12,
        lineHeight: lineHeight(12, 1.2),
        color: colors.muted,
        fontVariant: ['tabular-nums'],
    },
    cohortSelected: {
        color: colors.ink,
        fontWeight: '700',
    },
    cohortSize: {
        fontSize: 10,
        lineHeight: lineHeight(10, 1.2),
        color: colors.tertiary,
        fontVariant: ['tabular-nums'],
    },
    periods: {
        flex: 1,
    },
    head: {
        height: 22,
        fontSize: 11,
        lineHeight: 16,
        fontWeight: '600',
        color: colors.tertiary,
    },
    headRow: {
        flexDirection: 'row',
    },
    headCell: {
        width: CELL_WIDTH + CELL_GAP,
        textAlign: 'center',
    },
    cellRow: {
        flexDirection: 'row',
        height: CELL_HEIGHT + CELL_GAP,
    },
    cell: {
        width: CELL_WIDTH,
        height: CELL_HEIGHT,
        marginRight: CELL_GAP,
        borderRadius: 4,
        alignItems: 'center',
        justifyContent: 'center',
    },
    cellActive: {
        borderWidth: 2,
        borderColor: colors.ink,
    },
    cellText: {
        fontSize: 12,
        fontWeight: '600',
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    cellTextLight: {
        color: colors.white,
    },
    callout: {
        ...type.meta,
        color: colors.secondary,
        marginTop: 10,
        fontVariant: ['tabular-nums'],
    },
    empty: {
        ...type.metaSmall,
        color: colors.muted,
        paddingVertical: 8,
    },
}))
