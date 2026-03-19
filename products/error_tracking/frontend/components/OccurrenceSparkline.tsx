import { useCallback, useEffect, useMemo, useRef } from 'react'

import { IconTrending } from '@posthog/icons'

import type { Chart } from 'lib/Chart'
import { getColorVar } from 'lib/colors'
import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'
import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'

import { useDefaultSparklineColorVars, useSparklineOptions } from '../hooks/use-sparkline-options'
import { SparklineData, SparklineOptions } from './SparklineChart/SparklineChart'

const STRIPE_SIZE = 10

function createSpikePatternCanvas(): HTMLCanvasElement {
    const s = STRIPE_SIZE
    const canvas = document.createElement('canvas')
    canvas.width = s
    canvas.height = s
    const ctx = canvas.getContext('2d')
    if (!ctx) {
        return canvas
    }

    ctx.fillStyle = getColorVar('brand-yellow')
    ctx.fillRect(0, 0, s, s)

    ctx.fillStyle = 'rgba(255,255,255,0.4)'
    for (let y = 0; y < s; y++) {
        for (let x = 0; x < s; x++) {
            if ((x + y) % s >= s / 2) {
                ctx.fillRect(x, y, 1, 1)
            }
        }
    }

    return canvas
}

let sharedPatternCanvas: HTMLCanvasElement | null = null

let sharedHoverPatternCanvas: HTMLCanvasElement | null = null

function createSpikeHoverPatternCanvas(): HTMLCanvasElement {
    if (!sharedPatternCanvas) {
        sharedPatternCanvas = createSpikePatternCanvas()
    }
    const s = STRIPE_SIZE
    const canvas = document.createElement('canvas')
    canvas.width = s
    canvas.height = s
    const ctx = canvas.getContext('2d')
    if (!ctx) {
        return canvas
    }
    ctx.drawImage(sharedPatternCanvas, 0, 0)
    ctx.fillStyle = 'rgba(0,0,0,0.15)'
    ctx.fillRect(0, 0, s, s)
    return canvas
}

function createSpikePattern(): CanvasPattern | null {
    if (!sharedPatternCanvas) {
        sharedPatternCanvas = createSpikePatternCanvas()
    }
    const ctx = document.createElement('canvas').getContext('2d')
    return ctx?.createPattern(sharedPatternCanvas, 'repeat') ?? null
}

function createSpikeHoverPattern(): CanvasPattern | null {
    if (!sharedHoverPatternCanvas) {
        sharedHoverPatternCanvas = createSpikeHoverPatternCanvas()
    }
    const ctx = document.createElement('canvas').getContext('2d')
    return ctx?.createPattern(sharedHoverPatternCanvas, 'repeat') ?? null
}

type StripeAnimationCallback = (transform: DOMMatrix) => void

const stripeAnimationSubscribers = new Set<StripeAnimationCallback>()
let stripeAnimationFrameId: number | null = null
let stripeAnimationOffset = 0
const STRIPE_SPEED = STRIPE_SIZE / 110

function stripeAnimationTick(): void {
    stripeAnimationOffset = (stripeAnimationOffset + STRIPE_SPEED) % STRIPE_SIZE
    const transform = new DOMMatrix().translateSelf(0, -stripeAnimationOffset)
    for (const cb of stripeAnimationSubscribers) {
        cb(transform)
    }
    stripeAnimationFrameId = requestAnimationFrame(stripeAnimationTick)
}

function startStripeAnimationTicker(): void {
    if (stripeAnimationFrameId === null) {
        stripeAnimationFrameId = requestAnimationFrame(stripeAnimationTick)
    }
}

function stopStripeAnimationTicker(): void {
    if (stripeAnimationSubscribers.size === 0 && stripeAnimationFrameId !== null) {
        cancelAnimationFrame(stripeAnimationFrameId)
        stripeAnimationFrameId = null
    }
}

function hasSpikeInBin(datumTime: number, binSizeMs: number, spikeTimestamps: number[]): boolean {
    return spikeTimestamps.some((st) => st >= datumTime && st < datumTime + binSizeMs)
}

interface BuildResult {
    series: any[]
    spikeFlags: boolean[]
}

function buildSeriesData(
    data: SparklineData,
    options: SparklineOptions,
    spikeEvents: ErrorTrackingSpikeEvent[],
    spikePattern: CanvasPattern | null,
    spikeHoverPattern: CanvasPattern | null
): BuildResult {
    const series: any = {
        values: data.map((d) => d.value),
        name: 'Occurrences',
        color: options.backgroundColor,
        hoverColor: options.hoverBackgroundColor,
    }

    let spikeFlags: boolean[] = []

    if (spikeEvents.length > 0 && data.length >= 2 && spikePattern) {
        const binSizeMs = data[1].date.getTime() - data[0].date.getTime()
        const spikeTimestamps = spikeEvents.map((s) => new Date(s.detected_at).getTime())
        spikeFlags = data.map((datum) => hasSpikeInBin(datum.date.getTime(), binSizeMs, spikeTimestamps))
        series.barColors = spikeFlags.map((isSpike) => (isSpike ? spikePattern : options.backgroundColor))
        series.barHoverColors = spikeFlags.map((isSpike) =>
            isSpike ? (spikeHoverPattern ?? spikePattern) : options.hoverBackgroundColor
        )
    }

    return { series: [series], spikeFlags }
}

export function OccurrenceSparkline({
    data,
    className,
    displayXAxis = false,
    spikeEvents = [],
}: {
    data: SparklineData
    className?: string
    displayXAxis?: boolean
    spikeEvents?: ErrorTrackingSpikeEvent[]
}): JSX.Element {
    const colorVars = useDefaultSparklineColorVars()
    const options = useSparklineOptions({
        backgroundColor: colorVars[0],
        hoverBackgroundColor: colorVars[1],
    })

    const chartInstanceRef = useRef<Chart | null>(null)
    const spikePatternRef = useRef<CanvasPattern | null>(null)
    const spikeHoverPatternRef = useRef<CanvasPattern | null>(null)
    const hasSpikes = spikeEvents.length > 0

    const [occurrences, labels, labelRenderer, spikeFlags] = useMemo(() => {
        const pattern = hasSpikes ? createSpikePattern() : null
        const hoverPattern = hasSpikes ? createSpikeHoverPattern() : null
        spikePatternRef.current = pattern
        spikeHoverPatternRef.current = hoverPattern

        const result = buildSeriesData(data, options, spikeEvents, pattern, hoverPattern)
        return [
            result.series,
            data.map((value) => dayjs(value.date).toISOString()),
            (label: string) => dayjs(label).format('D MMM YYYY HH:mm (UTC)'),
            result.spikeFlags,
        ]
    }, [data, options, spikeEvents, hasSpikes])

    const renderTooltipSeries = useCallback(
        (label: React.ReactNode, dataIndex: number): React.ReactNode => {
            if (!spikeFlags[dataIndex]) {
                return label
            }
            return (
                <span className="inline-flex items-center gap-1">
                    {label}
                    <span className="inline-flex items-center gap-0.5 text-warning-dark font-semibold">
                        <IconTrending className="text-sm" />
                        Spike
                    </span>
                </span>
            )
        },
        [spikeFlags]
    )

    useEffect(() => {
        if (!hasSpikes) {
            return
        }

        const animate: StripeAnimationCallback = (transform) => {
            const pattern = spikePatternRef.current
            const hoverPattern = spikeHoverPatternRef.current
            const chart = chartInstanceRef.current
            if (pattern && chart?.canvas) {
                pattern.setTransform(transform)
                hoverPattern?.setTransform(transform)
                chart.update('none')
            }
        }

        stripeAnimationSubscribers.add(animate)
        startStripeAnimationTicker()
        return () => {
            stripeAnimationSubscribers.delete(animate)
            stopStripeAnimationTicker()
        }
    }, [hasSpikes])

    const withXScale = useCallback(
        (scale: AnyScaleOptions) =>
            ({
                ...scale,
                type: 'timeseries',
                ticks: { display: true, maxRotation: 0, maxTicksLimit: 5, font: { size: 10, lineHeight: 1 } },
                time: { unit: 'day', displayFormats: { day: 'D MMM' } },
            }) as AnyScaleOptions,
        []
    )

    return (
        <Sparkline
            className={className}
            data={occurrences}
            labels={labels}
            renderLabel={labelRenderer}
            withXScale={displayXAxis ? withXScale : undefined}
            chartInstanceRef={chartInstanceRef}
            renderTooltipSeries={hasSpikes ? renderTooltipSeries : undefined}
        />
    )
}
