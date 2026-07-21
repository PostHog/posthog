/* eslint-disable react/forbid-dom-props -- prototype overlay positions come from d3 scales */
/**
 * PROTOTYPE — THROWAWAY, DO NOT SHIP. See PROTOTYPE.md in this folder.
 *
 * Question: with "compare against" enabled, the funnel steps chart scales both periods against the
 * larger period's entrants, so only the larger period's first step reads 100% on the single percent
 * axis. Should the chart get a second value axis, and what should each axis show?
 *
 * Plan: three variants + the live rendering, on the existing funnel insight route, switchable via
 * `?funnel_axes_variant=` or the floating bottom pill. Dev builds only, pure compare funnels only.
 */
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useEffect, useMemo } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { useChartLayout } from '@posthog/quill-charts'
import type { FunnelChartConfig, Series } from '@posthog/quill-charts'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { funnelComparePeriodDateRange } from 'scenes/funnels/funnelUtils'

import type { FunnelStepWithConversionMetrics } from '~/types'

import { RATE_TO_PERCENT } from '../../shared/funnelBarHorizontalShared'
import type { FunnelStepsBarSeriesMeta } from '../funnelStepsBarTransforms'

const VARIANT_PARAM = 'funnel_axes_variant'

type VariantKey = 'live' | 'A' | 'B' | 'C'

const VARIANTS: { key: VariantKey; name: string; description: string }[] = [
    {
        key: 'live',
        name: 'Live (shared axis)',
        description: 'Production rendering: one percent axis, both periods scaled to the larger period.',
    },
    {
        key: 'A',
        name: 'Twin percent axes',
        description:
            'Each period normalized to its own entrants — both first steps read 100%. Left axis = this period, right axis = previous. Bar heights compare conversion rates directly; the volume difference is no longer visible.',
    },
    {
        key: 'B',
        name: 'Volume-true + second axis',
        description:
            "Bars exactly as today (volume-true, blank gap above the smaller period). Adds a right axis with the smaller period's own 0–100% compressed to its entry level, so its first step also reads 100% — on its axis.",
    },
    {
        key: 'C',
        name: 'Count axes',
        description:
            'Bars as in A (each period = its own 100%), but the axes are labeled in absolute user counts per period, so the axis carries the volume difference the bars no longer show.',
    },
]

interface PeriodInfo {
    breakdownIndex: number
    label: 'current' | 'previous'
    color: string | undefined
    /** First-step count of this period. */
    entrants: number
    /** entrants / max(entrants of both periods) — where this period's 100% sits on the shared scale. */
    entryShare: number
    /** Per-step conversion as % of this period's own entrants. */
    selfPercentData: number[]
}

interface PrototypeAxisSpec {
    side: 'left' | 'right'
    color?: string
    title?: string | null
    /** Label the primary scale's own ticks (0–100). */
    scaleTickLabel?: (tick: number) => string
    /** Fixed ticks in primary-scale units — for axes whose scale differs from the primary one. */
    fixedTicks?: { value: number; label: string }[]
}

export interface FunnelCompareAxesPrototypeRender {
    series: Series<FunnelStepsBarSeriesMeta>[]
    config: FunnelChartConfig
    /** Render as a FunnelChart child (draws the prototype axes inside the chart wrapper). */
    overlay: JSX.Element | null
    /** Floating variant switcher, portaled to document.body. */
    switcher: JSX.Element
}

const PROTOTYPE_MARGINS = { left: 48, right: 56, top: 28 }

function resolvePeriods(
    steps: FunnelStepWithConversionMetrics[],
    series: Series<FunnelStepsBarSeriesMeta>[]
): { current: PeriodInfo; previous: PeriodInfo } | null {
    // Pure compare only: exactly one current + one previous series, no breakdown values.
    if (series.length !== 2 || steps.length === 0 || !series.every((s) => s.meta?.compareLabel != null)) {
        return null
    }
    const infos = series.map((s): PeriodInfo => {
        const breakdownIndex = s.meta?.breakdownIndex ?? 0
        return {
            breakdownIndex,
            label: s.meta?.compareLabel === 'previous' ? 'previous' : 'current',
            color: s.color,
            entrants: steps[0].nested_breakdown?.[breakdownIndex]?.count ?? 0,
            entryShare: 0,
            selfPercentData: steps.map(
                (step) => (step.nested_breakdown?.[breakdownIndex]?.conversionRates.total ?? 0) * RATE_TO_PERCENT
            ),
        }
    })
    const maxEntrants = Math.max(...infos.map((p) => p.entrants))
    if (maxEntrants <= 0) {
        return null
    }
    for (const info of infos) {
        info.entryShare = info.entrants / maxEntrants
    }
    const current = infos.find((p) => p.label === 'current')
    const previous = infos.find((p) => p.label === 'previous')
    return current && previous ? { current, previous } : null
}

const percentTick = (tick: number): string => `${Math.round(tick)}%`

function buildVariant(
    variant: VariantKey,
    periods: { current: PeriodInfo; previous: PeriodInfo },
    series: Series<FunnelStepsBarSeriesMeta>[],
    periodTitles: { current: string | null; previous: string | null }
): { series: Series<FunnelStepsBarSeriesMeta>[]; axes: PrototypeAxisSpec[] } {
    const { current, previous } = periods
    const selfNormalized = series.map((s) => ({
        ...s,
        data: (s.meta?.compareLabel === 'previous' ? previous : current).selfPercentData,
        trackData: undefined, // no blank volume gap — each period's drop-off track runs to its own 100%
    }))

    switch (variant) {
        case 'A':
            return {
                series: selfNormalized,
                axes: [
                    { side: 'left', color: current.color, title: periodTitles.current, scaleTickLabel: percentTick },
                    {
                        side: 'right',
                        color: previous.color,
                        title: periodTitles.previous,
                        scaleTickLabel: percentTick,
                    },
                ],
            }
        case 'B': {
            const [larger, smaller] =
                current.entryShare >= previous.entryShare ? [current, previous] : [previous, current]
            return {
                series,
                axes: [
                    {
                        side: 'left',
                        color: larger.color,
                        title: periodTitles[larger.label],
                        scaleTickLabel: percentTick,
                    },
                    {
                        side: 'right',
                        color: smaller.color,
                        title: periodTitles[smaller.label],
                        // The smaller period's own 0–100%, compressed so its 100% sits at its entry level.
                        fixedTicks: [0, 25, 50, 75, 100].map((tick) => ({
                            value: smaller.entryShare * tick,
                            label: `${tick}%`,
                        })),
                    },
                ],
            }
        }
        case 'C':
            return {
                series: selfNormalized,
                axes: [
                    {
                        side: 'left',
                        color: current.color,
                        title: periodTitles.current,
                        scaleTickLabel: (tick) => humanFriendlyLargeNumber((tick / 100) * current.entrants),
                    },
                    {
                        side: 'right',
                        color: previous.color,
                        title: periodTitles.previous,
                        scaleTickLabel: (tick) => humanFriendlyLargeNumber((tick / 100) * previous.entrants),
                    },
                ],
            }
        default:
            return { series, axes: [] }
    }
}

/** Draws the prototype value axes as absolutely-positioned labels inside the chart wrapper,
 *  mirroring the geometry of the built-in AxisLabels (which the prototype config hides). */
function PrototypeAxesOverlay({ axes }: { axes: PrototypeAxisSpec[] }): JSX.Element {
    const { scales, dimensions } = useChartLayout()
    const scaleTicks = scales.yTicks()
    const plotBottom = dimensions.plotTop + dimensions.plotHeight

    return (
        <>
            {axes.map((axis) => {
                const edge =
                    axis.side === 'left'
                        ? { right: dimensions.width - dimensions.plotLeft + 8 }
                        : { left: dimensions.plotLeft + dimensions.plotWidth + 8 }
                const ticks = [
                    ...(axis.scaleTickLabel
                        ? scaleTicks.map((tick) => ({ value: tick, label: axis.scaleTickLabel!(tick) }))
                        : []),
                    ...(axis.fixedTicks ?? []),
                ]
                return (
                    <div key={axis.side}>
                        {ticks.map(({ value, label }) => {
                            const y = scales.y(value)
                            if (!isFinite(y) || y < dimensions.plotTop - 1 || y > plotBottom + 1) {
                                return null
                            }
                            return (
                                <div
                                    key={value}
                                    className="pointer-events-none absolute whitespace-nowrap text-xs"
                                    style={{ ...edge, top: y, transform: 'translateY(-50%)', color: axis.color }}
                                >
                                    {label}
                                </div>
                            )
                        })}
                        {axis.title && (
                            <div
                                className="pointer-events-none absolute top-1 whitespace-nowrap text-[10px] font-semibold"
                                style={{
                                    color: axis.color,
                                    ...(axis.side === 'left' ? { left: 4 } : { right: 4 }),
                                }}
                            >
                                {axis.title}
                            </div>
                        )}
                    </div>
                )
            })}
        </>
    )
}

function PrototypeSwitcher({ variant }: { variant: VariantKey }): JSX.Element {
    const index = Math.max(
        0,
        VARIANTS.findIndex((v) => v.key === variant)
    )

    const cycle = useCallback(
        (direction: 1 | -1): void => {
            const next = VARIANTS[(index + direction + VARIANTS.length) % VARIANTS.length]
            const { location, searchParams, hashParams } = router.values
            router.actions.replace(location.pathname, { ...searchParams, [VARIANT_PARAM]: next.key }, hashParams)
        },
        [index]
    )

    useEffect(() => {
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') {
                return
            }
            const target = event.target as HTMLElement | null
            if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
                return
            }
            cycle(event.key === 'ArrowLeft' ? -1 : 1)
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [cycle])

    const active = VARIANTS[index]

    // Plain `fixed` (no portal — react-dom isn't a product_analytics dependency, and this is throwaway).
    return (
        <div
            className="fixed bottom-4 left-1/2 z-[9999] flex -translate-x-1/2 items-center gap-1 rounded-full border border-accent bg-surface-primary py-1 pl-1 pr-3 shadow-lg"
            title={active.description}
        >
            <LemonButton
                size="xsmall"
                icon={<IconChevronLeft />}
                onClick={() => cycle(-1)}
                tooltip="Previous variant"
            />
            <LemonButton size="xsmall" icon={<IconChevronRight />} onClick={() => cycle(1)} tooltip="Next variant" />
            <span className="text-xs font-semibold">
                PROTOTYPE&ensp;{active.key} — {active.name}
            </span>
        </div>
    )
}

/** Entry point grafted into FunnelStepsBarChart. Returns null (production rendering, no prototype
 *  chrome) outside dev builds or when the funnel isn't a pure compare-against-previous funnel. */
export function useFunnelCompareAxesPrototype({
    steps,
    series,
    baseConfig,
    resolvedDateRange,
    compareTo,
}: {
    steps: FunnelStepWithConversionMetrics[]
    series: Series<FunnelStepsBarSeriesMeta>[]
    baseConfig: FunnelChartConfig
    resolvedDateRange?: Parameters<typeof funnelComparePeriodDateRange>[1]
    compareTo?: string | null
}): FunnelCompareAxesPrototypeRender | null {
    const isDev = process.env.NODE_ENV === 'development'
    const { searchParams } = useValues(router)
    const rawVariant = searchParams[VARIANT_PARAM]
    const variant: VariantKey = VARIANTS.some((v) => v.key === rawVariant) ? (rawVariant as VariantKey) : 'live'

    const periods = useMemo(() => (isDev ? resolvePeriods(steps, series) : null), [isDev, steps, series])

    const model = useMemo(() => {
        if (!periods) {
            return null
        }
        const periodTitles = {
            current: funnelComparePeriodDateRange('current', resolvedDateRange, compareTo) ?? 'This period',
            previous: funnelComparePeriodDateRange('previous', resolvedDateRange, compareTo) ?? 'Previous period',
        }
        return buildVariant(variant, periods, series, periodTitles)
    }, [periods, variant, series, resolvedDateRange, compareTo])

    const config = useMemo<FunnelChartConfig>(
        () =>
            variant === 'live'
                ? baseConfig
                : { ...baseConfig, hideValueAxis: true, margins: { ...baseConfig.margins, ...PROTOTYPE_MARGINS } },
        [variant, baseConfig]
    )

    if (!isDev || !periods || !model) {
        return null
    }

    return {
        series: model.series,
        config,
        overlay: model.axes.length > 0 ? <PrototypeAxesOverlay axes={model.axes} /> : null,
        switcher: <PrototypeSwitcher variant={variant} />,
    }
}
