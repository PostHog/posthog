import { useId } from 'react'

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { RolloutStep } from './releaseRollout'

interface Point {
    x: number
    y: number
}

function shortLabel(step: RolloutStep): string {
    return step.label === 'Everyone' ? '100%' : step.label
}

function range(step: RolloutStep, start: dayjs.Dayjs, today: dayjs.Dayjs): string {
    const from = dayjs(step.from)
    if (step.upcoming) {
        return `Scheduled for ${from.format('D MMM')}`
    }
    const to = dayjs(step.to)
    const since = from.isBefore(start) ? `before ${start.format('D MMM')}` : from.format('D MMM')
    if (to.isSame(today, 'day') || to.isAfter(today)) {
        return `Since ${since}`
    }
    return `${since.charAt(0).toUpperCase()}${since.slice(1)} to ${to.format('D MMM')}`
}

export function ReleaseRolloutChart({
    steps,
    start,
    days,
    dayWidth,
    height,
    labelRoom,
    className,
    style,
    note,
    color,
}: {
    steps: RolloutStep[]
    start: dayjs.Dayjs
    days: number
    dayWidth: number
    height: number
    labelRoom: number
    className?: string
    style?: React.CSSProperties
    note?: string
    color?: string
}): JSX.Element | null {
    const gradientId = `rollout-${useId().replace(/:/g, '')}`
    const width = days * dayWidth
    const today = dayjs()
    const xOf = (date: string): number => {
        const index = dayjs(date).startOf('day').diff(start, 'day')
        return index < 0 ? 0 : index >= days ? width : (index + 0.5) * dayWidth
    }
    const base = height - 6
    const yOf = (percent: number): number => labelRoom + (1 - percent / 100) * (base - labelRoom - 1)
    const visible = steps.filter((step) => xOf(step.to) > 0 && xOf(step.from) < width)
    if (!visible.length) {
        return null
    }
    const past = visible.filter((step) => !step.upcoming)
    const upcoming = visible.filter((step) => step.upcoming)

    const linePoints = (list: RolloutStep[]): Point[] =>
        list.flatMap((step) => [
            { x: xOf(step.from), y: yOf(step.percent) },
            { x: xOf(step.to), y: yOf(step.percent) },
        ])
    const toPath = (points: Point[]): string =>
        points.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(' ')

    const tail = 2 * dayWidth
    const pastPoints = linePoints(past)
    const lastPast = pastPoints[pastPoints.length - 1]
    const futurePoints = upcoming.length
        ? [
              ...(lastPast ? [lastPast, { x: xOf(upcoming[0].from), y: lastPast.y }] : []),
              ...upcoming.flatMap((step, index) => {
                  const from = xOf(step.from)
                  const next = upcoming[index + 1]
                  const to = next ? xOf(next.from) : Math.min(from + tail, width)
                  return [
                      { x: from, y: yOf(step.percent) },
                      { x: to, y: yOf(step.percent) },
                  ]
              }),
          ]
        : []
    const current = past[past.length - 1]

    const textOf = (step: RolloutStep): string =>
        step.upcoming
            ? `${shortLabel(step)} on ${dayjs(step.from).format('D MMM')}`
            : step === current && note
              ? `${shortLabel(step)} · ${note}`
              : shortLabel(step)
    const widthOf = (step: RolloutStep): number => textOf(step).length * 6 + 10
    const candidates = [...past, ...upcoming].map((step) => ({ step, x: xOf(step.from), y: yOf(step.percent) }))
    const required = candidates.filter(
        ({ step }) => step === past[0] || step === current || step === upcoming[upcoming.length - 1]
    )
    const GAP = 32
    const SIGNIFICANT = 15
    const clear = (x: number, step: RolloutStep, others: typeof candidates): boolean =>
        others.every((other) => x + widthOf(step) + GAP <= other.x || other.x + widthOf(other.step) + GAP <= x)
    const optional: typeof candidates = []
    let lastPercent = past[0]?.percent ?? 0
    for (const candidate of candidates) {
        if (required.includes(candidate)) {
            lastPercent = candidate.step.percent
            continue
        }
        if (
            Math.abs(candidate.step.percent - lastPercent) >= SIGNIFICANT &&
            clear(candidate.x, candidate.step, [...required, ...optional])
        ) {
            optional.push(candidate)
            lastPercent = candidate.step.percent
        }
    }
    const shown = [...required, ...optional]

    return (
        <TooltipProvider>
            <div className={cn('relative', className)} style={{ ...style, width, height }}>
                <svg
                    width={width}
                    height={height}
                    className="absolute inset-0 overflow-visible text-foreground"
                    style={color ? { color } : undefined}
                    aria-hidden
                >
                    <defs>
                        <linearGradient
                            id={gradientId}
                            gradientUnits="userSpaceOnUse"
                            x1="0"
                            y1={yOf(100)}
                            x2="0"
                            y2={base}
                        >
                            <stop offset="0%" stopColor="currentColor" stopOpacity={0.16} />
                            <stop offset="100%" stopColor="currentColor" stopOpacity={0} />
                        </linearGradient>
                    </defs>
                    {past
                        .filter((step) => step.percent > 0)
                        .map((step) => {
                            const left = xOf(step.from)
                            const top = yOf(step.percent)
                            return (
                                <rect
                                    key={`area-${step.from}`}
                                    x={left}
                                    y={top}
                                    width={Math.max(xOf(step.to) - left, 0)}
                                    height={Math.max(base - top, 0)}
                                    fill={`url(#${gradientId})`}
                                />
                            )
                        })}
                    {pastPoints.length > 0 && (
                        <path
                            d={toPath(pastPoints)}
                            className="fill-none stroke-current"
                            strokeWidth={2}
                            strokeLinejoin="round"
                            strokeLinecap="round"
                        />
                    )}
                    {futurePoints.length > 0 && (
                        <path
                            d={toPath(futurePoints)}
                            className="fill-none stroke-current opacity-60"
                            strokeWidth={2}
                            strokeDasharray="3 4"
                            strokeLinejoin="round"
                            strokeLinecap="round"
                        />
                    )}
                    {upcoming.map((step) => (
                        <circle
                            key={`next-${step.from}`}
                            cx={xOf(step.from)}
                            cy={yOf(step.percent)}
                            r={3.5}
                            strokeWidth={1.5}
                            className="fill-[var(--background)] stroke-current"
                        />
                    ))}
                </svg>
                {shown.map(({ step, x, y }) => {
                    const left = x + (step.upcoming ? 7 : 4)
                    const flip = left + widthOf(step) > width
                    return (
                        <span
                            key={`label-${step.from}`}
                            className={cn(
                                'pointer-events-none absolute whitespace-nowrap text-[10px] leading-none tabular-nums',
                                step === current ? 'font-semibold text-foreground' : 'font-medium text-muted-foreground'
                            )}
                            style={
                                flip
                                    ? { right: width - x + (step.upcoming ? 7 : 4), top: Math.max(0, y - 13) }
                                    : { left, top: Math.max(0, y - 13) }
                            }
                        >
                            {step === current && note ? (
                                <>
                                    {shortLabel(step)}
                                    <span className="font-medium text-muted-foreground"> · {note}</span>
                                </>
                            ) : (
                                textOf(step)
                            )}
                        </span>
                    )
                })}
                {visible.map((step, index) => {
                    const left = xOf(step.from)
                    const right = step.upcoming && !visible[index + 1] ? Math.min(left + tail, width) : xOf(step.to)
                    const span = Math.max(right - left, 6)
                    return (
                        <Tooltip key={`hit-${step.from}`}>
                            <TooltipTrigger
                                render={
                                    <span
                                        className="absolute top-0 block"
                                        style={{ left, width: span, height }}
                                        data-attr="release-rollout-step"
                                    />
                                }
                            />
                            <TooltipContent>
                                <span className="flex flex-col gap-0.5">
                                    <span className="font-semibold">
                                        {step.label === 'Everyone'
                                            ? 'Everyone'
                                            : `${step.label}${step.label.endsWith('%') ? ' rollout' : ''}`}
                                    </span>
                                    <span className="opacity-70">{range(step, start, today)}</span>
                                </span>
                            </TooltipContent>
                        </Tooltip>
                    )
                })}
            </div>
        </TooltipProvider>
    )
}
