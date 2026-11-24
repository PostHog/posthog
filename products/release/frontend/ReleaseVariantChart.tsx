import { Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { VariantPoint } from './releaseLaneInsights'
import { SPAN_LOOK, Scale, x } from './releaseTracks'

const HEADER = 52
const FOOTER = 8

function variantColor(variant: string, index: number): string {
    return variant === 'control'
        ? 'color-mix(in oklab, var(--muted-foreground) 45%, transparent)'
        : `color-mix(in oklab, ${SPAN_LOOK.experiment.color} ${Math.max(35, 75 - index * 20)}%, transparent)`
}

function format(value: number): string {
    return value >= 100 ? String(Math.round(value)) : String(Math.round(value * 100) / 100)
}

export function ReleaseVariantChart({
    series,
    cumulative,
    metricName,
    scale,
    height,
    stickyOffset = 0,
}: {
    series: VariantPoint[]
    cumulative: boolean
    metricName: string
    scale: Scale
    height: number
    stickyOffset?: number
}): JSX.Element {
    const points = series.filter((point) => !dayjs(point.day).isBefore(scale.start, 'day'))
    const variants = [...new Set(points.map((point) => point.variant))].sort((a, b) =>
        a === 'control' ? -1 : b === 'control' ? 1 : a.localeCompare(b)
    )
    const byDay = new Map<string, Map<string, number>>()
    for (const point of points) {
        byDay.set(point.day, (byDay.get(point.day) ?? new Map()).set(point.variant, point.value))
    }
    const peak = Math.max(0, ...points.map((point) => point.value))
    const area = height - HEADER - FOOTER
    const group = Math.max(variants.length * 3, Math.round(scale.day * 0.7))
    const bar = Math.max(2, Math.floor(group / Math.max(1, variants.length)) - 1)

    return (
        <div className="relative" style={{ height }} data-attr="release-lane-variants">
            <div className="sticky z-10 flex w-fit flex-col px-3 pt-2" style={{ left: stickyOffset }}>
                <Text size="xs" weight="medium">
                    {cumulative ? `${metricName}, so far` : `${metricName}, each day`}
                </Text>
                <div className="flex items-center gap-3">
                    {variants.map((variant, index) => (
                        <span key={variant} className="flex items-center gap-1">
                            <span
                                className="inline-block size-2 rounded-[2px]"
                                style={{ backgroundColor: variantColor(variant, index) }}
                            />
                            <Text size="xs" variant="muted" render={<span />}>
                                {variant}
                            </Text>
                        </span>
                    ))}
                </div>
            </div>
            {[...byDay.entries()].map(([day, values]) => {
                const left = x(day, scale) + Math.round((scale.day - variants.length * (bar + 1)) / 2)
                return (
                    <Tooltip key={day} trackCursorAxis="x">
                        <TooltipTrigger
                            render={
                                <div
                                    className="absolute flex items-end gap-px"
                                    style={{ left, bottom: FOOTER, height: area }}
                                />
                            }
                        >
                            {variants.map((variant, index) => {
                                const value = values.get(variant) ?? 0
                                return (
                                    <div
                                        key={variant}
                                        className="rounded-t-[2px]"
                                        style={{
                                            width: bar,
                                            height: peak ? Math.max(2, Math.round((value / peak) * area)) : 0,
                                            backgroundColor: variantColor(variant, index),
                                        }}
                                    />
                                )
                            })}
                        </TooltipTrigger>
                        <TooltipContent>
                            <span className="tabular-nums">
                                {`${dayjs(day).format('D MMM')}: ${variants
                                    .map((variant) => `${variant} ${format(values.get(variant) ?? 0)}`)
                                    .join(' · ')}`}
                            </span>
                        </TooltipContent>
                    </Tooltip>
                )
            })}
        </div>
    )
}
