import { type ReactElement, useCallback } from 'react'
import { Text, View } from 'react-native'

import { groupThousands, plural } from '@/model/adapters/text'
import type { FunnelStepView, FunnelView } from '@/model/views'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useTheme } from '@/ui/theme'
import { lineHeight, radii, type } from '@/ui/tokens'

import { useItemChartAccessibility } from './accessibility/useChartAccessibility'
import { seriesColor } from './palette'
import { useItemSelection } from './selection/useItemSelection'
import type { ChartAccessibilityAction, ChartTrackingContext } from './types'

interface FunnelStepsProps {
    funnel: FunnelView
    /** The insight's name, for the spoken summary. */
    label: string
    /** Shows the total conversion above the steps. Tiles carry it in their meta line instead. */
    showSummary?: boolean
    selectionId?: string
    trackingContext?: ChartTrackingContext
    accessibilityActions?: readonly ChartAccessibilityAction[]
    testID?: string
}

/** "4.2%" under 10 percent, "38%" above, like the web's funnel bars. */
export function funnelPercent(value: number | null): string {
    if (value === null) {
        return '–'
    }
    return `${groupThousands(value, value < 10 ? 1 : 0)}%`
}

/** "52 s", "6 min", "2 h 14 min", "3 d 4 h". */
export function shortDuration(seconds: number): string {
    if (seconds < 60) {
        return `${Math.round(seconds)} s`
    }
    const minutes = Math.round(seconds / 60)
    if (minutes < 60) {
        return `${minutes} min`
    }
    const hours = Math.floor(minutes / 60)
    if (hours < 24) {
        const rest = minutes % 60
        return rest > 0 ? `${hours} h ${rest} min` : `${hours} h`
    }
    const days = Math.floor(hours / 24)
    const rest = hours % 24
    return rest > 0 ? `${days} d ${rest} h` : `${days} d`
}

function stepSentence(step: FunnelStepView, index: number): string {
    const parts = [`Step ${index + 1}, ${step.name}: ${plural(step.count, 'person', 'people')}`]
    if (index > 0) {
        parts.push(`${funnelPercent(step.percentOfFirst)} of step 1`)
        parts.push(`${funnelPercent(step.percentOfPrevious)} from the previous step`)
        if (step.droppedOff !== null) {
            parts.push(`${groupThousands(step.droppedOff)} dropped off`)
        }
        if (step.medianSeconds !== null) {
            parts.push(`median time ${shortDuration(step.medianSeconds)}`)
        }
    }
    return `${parts.join(', ')}.`
}

/** The total conversion, such as "14% converted from Viewed pricing to Paid". */
export function funnelSummary(funnel: FunnelView): string | null {
    const first = funnel.steps[0]
    const last = funnel.steps[funnel.steps.length - 1]
    if (!first || !last || funnel.steps.length < 2) {
        return null
    }
    return `${funnelPercent(funnel.conversion)} converted from ${first.name} to ${last.name}`
}

/**
 * A funnel as rows: each step's name and count, a bar as a share of step 1, and between steps the conversion and the
 * people who dropped off. A tap on a step selects it and shows the median time from the step before.
 */
export function FunnelSteps({
    funnel,
    label,
    showSummary = false,
    selectionId,
    trackingContext,
    accessibilityActions,
    testID,
}: FunnelStepsProps): ReactElement {
    const { colors, chartPalette } = useTheme()
    const styles = useStyles()
    const { steps } = funnel
    const selection = useItemSelection({
        selectionId,
        kind: 'funnel',
        seriesCount: 1,
        dataKey: funnel,
        trackingContext,
    })
    const describe = useCallback(
        (index: number) => {
            const step = steps[index]
            return step ? stepSentence(step, index) : ''
        },
        [steps]
    )
    const summary = funnelSummary(funnel)
    const a11y = useItemChartAccessibility({
        summary: [`${label}, funnel with ${plural(steps.length, 'step')}`, summary].filter(Boolean).join('. '),
        count: steps.length,
        selected: selection.selected,
        describe,
        select: (index) => selection.select(index, 'accessibility'),
        clear: () => selection.clear('back'),
        hint: 'Swipe up or down to move between steps.',
        actions: accessibilityActions,
    })

    if (steps.length === 0) {
        return (
            <Text style={styles.empty} testID={testID}>
                Nobody entered this funnel in this date range.
            </Text>
        )
    }
    const fill = seriesColor(0, chartPalette)
    return (
        <View ref={selection.viewRef} onTouchStart={selection.onTouchStart} testID={testID} {...a11y}>
            {showSummary && summary ? <Text style={styles.summary}>{summary}</Text> : null}
            <View style={styles.steps}>
                {steps.map((step, index) => {
                    const selected = selection.selected === index
                    const width = Math.max(0, Math.min(100, step.percentOfFirst ?? 0))
                    return (
                        <Pressable44
                            key={step.key}
                            onPress={() => selection.toggle(index)}
                            hitSlop={0}
                            pressedBackground={colors.sunken}
                            style={[styles.step, selected && styles.stepSelected]}
                            accessible={false}
                            testID={testID ? `${testID}-step-${index}` : undefined}
                        >
                            {index > 0 ? (
                                <Text style={styles.conversion}>
                                    {funnelPercent(step.percentOfPrevious)} from the previous step
                                    {step.droppedOff !== null
                                        ? ` · ${groupThousands(step.droppedOff)} dropped off`
                                        : ''}
                                </Text>
                            ) : null}
                            <View style={styles.row}>
                                <Text style={styles.name} numberOfLines={2}>
                                    {index + 1}. {step.name}
                                </Text>
                                <Text style={styles.count}>
                                    {groupThousands(step.count)} · {funnelPercent(step.percentOfFirst)}
                                </Text>
                            </View>
                            <View style={styles.track}>
                                <View style={[styles.fill, { width: `${width}%`, backgroundColor: fill }]} />
                            </View>
                            {selected && index > 0 ? (
                                <Text style={styles.detail}>
                                    {step.medianSeconds !== null
                                        ? `Median time from the previous step: ${shortDuration(step.medianSeconds)}`
                                        : 'No median time for this step.'}
                                </Text>
                            ) : null}
                        </Pressable44>
                    )
                })}
            </View>
            {funnel.breakdownValues > 0 ? (
                <Text style={styles.note}>
                    Counts add up {plural(funnel.breakdownValues, 'breakdown value')}. Open it on the web to compare
                    them.
                </Text>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    summary: {
        ...type.bodySmallStrong,
        color: colors.ink,
        marginBottom: 10,
    },
    steps: {
        gap: 4,
    },
    step: {
        minHeight: 44,
        gap: 5,
        paddingVertical: 4,
        paddingHorizontal: 6,
        marginHorizontal: -6,
        borderRadius: radii.markLarge,
    },
    stepSelected: {
        backgroundColor: colors.blueHighlight,
    },
    conversion: {
        fontSize: 12,
        lineHeight: lineHeight(12),
        color: colors.tertiary,
        fontVariant: ['tabular-nums'],
    },
    row: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        gap: 8,
    },
    name: {
        flex: 1,
        fontSize: 14,
        lineHeight: lineHeight(14),
        color: colors.ink,
    },
    count: {
        fontSize: 14,
        lineHeight: lineHeight(14),
        fontWeight: '700',
        color: colors.ink,
        fontVariant: ['tabular-nums'],
    },
    track: {
        height: 18,
        backgroundColor: colors.sunken,
        borderTopRightRadius: 4,
        borderBottomRightRadius: 4,
        overflow: 'hidden',
    },
    fill: {
        height: '100%',
        borderTopRightRadius: 4,
        borderBottomRightRadius: 4,
    },
    detail: {
        fontSize: 12,
        lineHeight: lineHeight(12),
        color: colors.secondary,
    },
    note: {
        ...type.metaSmall,
        color: colors.tertiary,
        marginTop: 10,
    },
    empty: {
        ...type.metaSmall,
        color: colors.muted,
        paddingVertical: 8,
    },
}))
