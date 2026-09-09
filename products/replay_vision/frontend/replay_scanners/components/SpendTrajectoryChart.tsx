import { memo } from 'react'

import { dayjs } from 'lib/dayjs'
import { clamp, compactNumber } from 'lib/utils/numbers'

import type { VisionQuotaApi } from '../../generated/api.schemas'
import { formatCreditCount, formatCreditNumber } from '../../utils/credits'
import type { SpendSeries } from '../visionUsageLogic'

const WIDTH = 640
const HEIGHT = 200
const PAD_LEFT = 34
const PAD_X = 8
const TOP = 34
const BASE = HEIGHT - 20
const LABEL_CLEARANCE = 12
// A reference line closer than this to the baseline reads as part of the axis.
const AXIS_CLEARANCE = 10
const ABOVE = -6

interface SpendTrajectoryChartProps {
    quota: VisionQuotaApi
    /** Settled credits per UTC day of the period, oldest first. */
    dailyCredits: SpendSeries
    /** Credits the period is projected to end on, already held at the limit where one applies. */
    projectedTotal: number
    /** When demand crosses the limit inside the period, the date the verdict computed for it. */
    capReachDate: dayjs.Dayjs | null
    /** Hex/token-resolved colour for the projection line, matching the verdict status. */
    statusVar: string
}

interface Point {
    x: number
    y: number
}

function pointsAttr(points: Point[]): string {
    return points.map((p) => `${Math.round(p.x * 10) / 10},${Math.round(p.y * 10) / 10}`).join(' ')
}

/** Labels live in HTML so they keep their font size while the SVG scales with the card. */
function Label({
    x,
    y,
    anchor = 'start',
    className = '',
    style,
    children,
}: {
    x: number
    y: number
    anchor?: 'start' | 'end' | 'middle'
    className?: string
    style?: React.CSSProperties
    children: React.ReactNode
}): JSX.Element {
    const translateX = anchor === 'end' ? '-100%' : anchor === 'middle' ? '-50%' : '0'
    return (
        <span
            className={`absolute text-xs leading-none whitespace-nowrap ${className}`}
            style={{
                left: `${(x / WIDTH) * 100}%`,
                top: `${(y / HEIGHT) * 100}%`,
                transform: `translate(${translateX}, -50%)`,
                ...style,
            }}
        >
            {children}
        </span>
    )
}

/** Marks a point on the line. HTML, so a stretched viewBox cannot flatten it into an ellipse. */
function Dot({ x, y, color }: { x: number; y: number; color: string }): JSX.Element {
    return (
        <span
            className="absolute size-1.5 rounded-full"
            style={{
                left: `${(x / WIDTH) * 100}%`,
                top: `${(y / HEIGHT) * 100}%`,
                transform: 'translate(-50%, -50%)',
                background: color,
            }}
        />
    )
}

/**
 * Cumulative spend across the period against the limit: a solid line to today, a dashed projection
 * to period end, and a dashed line where the limit sits. Spend pauses at the limit, so the drawn
 * projection never exceeds it: when demand crosses, the line flattens at the crossing and the
 * crossing carries the date. Percentages stay off the chart.
 */
function SpendTrajectoryChartInner({
    quota,
    dailyCredits,
    projectedTotal,
    capReachDate,
    statusVar,
}: SpendTrajectoryChartProps): JSX.Element {
    // The ledger is bucketed by UTC day, so the axis is UTC too; a local axis would shift the curve by a day.
    const periodStart = dayjs.utc(quota.period_start)
    const periodEnd = dayjs.utc(quota.period_end)
    const periodDays = Math.max(periodEnd.diff(periodStart, 'day', true), 1)
    const todayDay = clamp(dayjs.utc().diff(periodStart, 'day', true), 0, periodDays)

    let runningTotal = 0
    const cumulative: { day: number; value: number }[] = []
    for (const entry of dailyCredits) {
        runningTotal += entry.credits
        // A day's bucket is complete at its end; today's is only as complete as the clock.
        const dayEnd = dayjs.utc(entry.date).diff(periodStart, 'day', true) + 1
        cumulative.push({ day: clamp(dayEnd, 0, todayDay), value: runningTotal })
    }
    // The card header reads `credits_used`, so today's point is that number and the ledger only gives the
    // curve its shape. The series is fetched alongside the quota and can be a moment newer, so only the
    // tail is pulled down to it: clamping every point would draw days of zero spend that never happened.
    const spentTotal = quota.credits_used
    if (cumulative.length > 0) {
        for (let i = cumulative.length - 1; i >= 0 && cumulative[i].value > spentTotal; i--) {
            cumulative[i] = { ...cumulative[i], value: spentTotal }
        }
        cumulative[cumulative.length - 1] = { ...cumulative[cumulative.length - 1], value: spentTotal }
    }

    // A zero or missing limit draws no cap; spend stops at a real one, so the drawn end never
    // exceeds it and demand only decides the slope. Cumulative spend cannot go down, so it never dips below today either.
    const cap = quota.credit_limit !== null && quota.credit_limit > 0 ? quota.credit_limit : null
    const demand = Math.max(projectedTotal, spentTotal)
    const endValue = cap !== null ? Math.min(demand, cap) : demand
    // The free allocation gets its own quieter line, unless it IS the limit (the free plan).
    const freeCredits = quota.free_monthly_credits
    const drawFreeLine = freeCredits > 0 && (cap === null || freeCredits < cap)
    const maxValue = Math.max(cap ?? 0, endValue, spentTotal, drawFreeLine ? freeCredits : 0, 1)
    const xForDay = (day: number): number => PAD_LEFT + (day / periodDays) * (WIDTH - PAD_LEFT - PAD_X)
    const yForCredits = (credits: number): number => BASE - (credits / maxValue) * (BASE - TOP)

    const spentPoints: Point[] =
        cumulative.length > 0
            ? cumulative.map((c) => ({ x: xForDay(c.day), y: yForCredits(c.value) }))
            : [{ x: xForDay(todayDay), y: yForCredits(spentTotal) }]
    const origin: Point = { x: xForDay(0), y: yForCredits(0) }
    const today: Point = spentPoints[spentPoints.length - 1]
    // A day-old period leaves no width to draw a line in; a lone dot reads better than a vertical stroke.
    const drawSpentLine = today.x - origin.x >= 1.5
    const end: Point = { x: xForDay(periodDays), y: yForCredits(endValue) }

    // The crossing sits on the verdict's date, so the dot, its label and the tile all name the same day.
    const crossingDay = capReachDate ? capReachDate.diff(periodStart, 'day', true) : null
    const crossingDate = capReachDate?.format('MMM D')
    const crossing: Point | null =
        cap !== null && crossingDay !== null && spentTotal < cap && crossingDay > todayDay && crossingDay <= periodDays
            ? { x: xForDay(crossingDay), y: yForCredits(cap) }
            : null
    const pausedAtLimit = cap !== null && spentTotal >= cap

    // Round tick steps (1/2/2.5/5 per decade) so y labels land on friendly numbers.
    const rawStep = maxValue / 4
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)))
    const stepChoice = [1, 2, 2.5, 5, 10].find((m) => m * magnitude >= rawStep) ?? 10
    const yStep = stepChoice * magnitude
    const yTicks: number[] = []
    for (let v = yStep; v <= maxValue; v += yStep) {
        yTicks.push(v)
    }
    const xTicks: number[] = []
    for (let day = 7; day <= periodDays - 3; day += 7) {
        xTicks.push(day)
    }

    const dangerVar = 'var(--danger)'
    const mutedVar = 'var(--muted)'
    const projectionLabel = `${periodEnd.format('MMM D')} · ~${formatCreditNumber(endValue)}`
    const limitY = cap !== null ? yForCredits(cap) : null
    const freeY = drawFreeLine ? yForCredits(freeCredits) : null
    // Two dotted reference lines an em apart read as one; drop the free one when it nearly touches the
    // limit line, or when it sits so low against the limit that it merges with the axis and its date labels.
    const showFreeLine =
        freeY !== null &&
        (limitY === null || Math.abs(freeY - limitY) >= LABEL_CLEARANCE) &&
        BASE - freeY >= AXIS_CLEARANCE

    // Labels sit above their anchor. Below a point is the filled area and the rising curve, so a label
    // blocked by a reference line climbs past it instead of dropping into the fill.
    const referenceYs = [limitY, freeY].filter((y): y is number => y !== null)
    const labelY = (anchorY: number): number => {
        let candidate = anchorY + ABOVE
        // Lowest line first, so a label pushed past one is then tested against the next one up.
        for (const reference of [...referenceYs].sort((a, b) => b - a)) {
            if (Math.abs(candidate - reference) < LABEL_CLEARANCE) {
                candidate = reference - LABEL_CLEARANCE
            }
        }
        return Math.max(candidate, 10)
    }
    // Today's label sits left of its dot unless the point hugs the axis, where it would run off the edge.
    const todayLabelLeft = today.x >= 60
    const todayLabelX = todayLabelLeft ? today.x - 9 : today.x + 9
    const todayLabelY = labelY(today.y)
    const endLabelY = labelY(end.y)
    const crossingLabelRight = crossing !== null && crossing.x + 90 <= WIDTH - PAD_X

    const caption = crossing
        ? `Hits the limit around ${crossingDate}. Scanning pauses until ${periodEnd.format('MMM D')}.`
        : pausedAtLimit
          ? `Scanning is paused at the limit until ${periodEnd.format('MMM D')}.`
          : null

    return (
        <div className="flex flex-col gap-1">
            <div className="relative w-full">
                {/* The box stretches to the card's width at a fixed height, so the chart stays wide and short. */}
                <svg
                    viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                    preserveAspectRatio="none"
                    className="block h-[200px] w-full"
                    role="img"
                    aria-label={
                        crossing
                            ? `Cumulative spend this period: ${formatCreditCount(spentTotal)} so far, projected to reach the ${formatCreditCount(cap ?? 0)} limit around ${crossingDate}`
                            : `Cumulative spend this period: ${formatCreditCount(spentTotal)} so far, projected ${formatCreditCount(endValue)} by ${periodEnd.format('MMMM D')}${cap !== null ? `, limit ${formatCreditCount(cap)}` : ''}`
                    }
                >
                    {yTicks.map((v) => (
                        <line
                            key={v}
                            x1={PAD_LEFT}
                            y1={yForCredits(v)}
                            x2={WIDTH - PAD_X}
                            y2={yForCredits(v)}
                            stroke="var(--border)"
                            vectorEffect="non-scaling-stroke"
                            strokeWidth={0.5}
                            opacity={0.6}
                        />
                    ))}
                    <line
                        x1={PAD_LEFT}
                        y1={TOP - 14}
                        x2={PAD_LEFT}
                        y2={BASE}
                        stroke="var(--border)"
                        vectorEffect="non-scaling-stroke"
                        strokeWidth={1}
                    />
                    {xTicks.map((day) => (
                        <line
                            key={day}
                            x1={xForDay(day)}
                            y1={BASE}
                            x2={xForDay(day)}
                            y2={BASE + 3}
                            stroke="var(--border)"
                            vectorEffect="non-scaling-stroke"
                            strokeWidth={1}
                        />
                    ))}
                    {limitY !== null && (
                        <line
                            x1={PAD_LEFT}
                            y1={limitY}
                            x2={WIDTH - PAD_X}
                            y2={limitY}
                            stroke={dangerVar}
                            vectorEffect="non-scaling-stroke"
                            strokeWidth={1}
                            strokeDasharray="2 3"
                        />
                    )}
                    {showFreeLine && freeY !== null && (
                        <line
                            x1={PAD_LEFT}
                            y1={freeY}
                            x2={WIDTH - PAD_X}
                            y2={freeY}
                            stroke={mutedVar}
                            vectorEffect="non-scaling-stroke"
                            strokeWidth={1}
                            strokeDasharray="2 3"
                            opacity={0.7}
                        />
                    )}
                    <line
                        x1={PAD_LEFT}
                        y1={BASE}
                        x2={WIDTH - PAD_X}
                        y2={BASE}
                        stroke="var(--border)"
                        vectorEffect="non-scaling-stroke"
                        strokeWidth={1}
                    />
                    {drawSpentLine && (
                        <>
                            <polygon
                                points={pointsAttr([origin, ...spentPoints, { x: today.x, y: BASE }])}
                                fill="currentColor"
                                opacity={0.06}
                            />
                            <polyline
                                points={pointsAttr([origin, ...spentPoints])}
                                fill="none"
                                stroke="currentColor"
                                vectorEffect="non-scaling-stroke"
                                strokeWidth={1.5}
                                strokeLinecap="round"
                            />
                        </>
                    )}
                    {crossing ? (
                        <>
                            <polyline
                                points={pointsAttr([today, crossing])}
                                fill="none"
                                stroke={dangerVar}
                                vectorEffect="non-scaling-stroke"
                                strokeWidth={1.5}
                                strokeDasharray="4 4"
                                strokeLinecap="round"
                            />
                        </>
                    ) : (
                        <>
                            <polyline
                                points={pointsAttr([today, end])}
                                fill="none"
                                stroke={pausedAtLimit ? dangerVar : statusVar}
                                vectorEffect="non-scaling-stroke"
                                strokeWidth={1.5}
                                strokeDasharray="4 4"
                                strokeLinecap="round"
                            />
                        </>
                    )}
                </svg>
                <div className="absolute inset-0 pointer-events-none" aria-hidden>
                    <Dot x={today.x} y={today.y} color="currentColor" />
                    {crossing ? (
                        <Dot x={crossing.x} y={crossing.y} color={dangerVar} />
                    ) : (
                        <Dot x={end.x} y={end.y} color={pausedAtLimit ? dangerVar : statusVar} />
                    )}
                    {yTicks.map((v) => (
                        <Label key={v} x={PAD_LEFT - 4} y={yForCredits(v)} anchor="end" className="text-muted">
                            {compactNumber(v)}
                        </Label>
                    ))}
                    <Label x={PAD_LEFT - 4} y={BASE} anchor="end" className="text-muted">
                        0
                    </Label>
                    {xTicks.map((day) => (
                        <Label key={day} x={xForDay(day)} y={HEIGHT - 8} anchor="middle" className="text-muted">
                            {periodStart.add(day, 'day').format('MMM D')}
                        </Label>
                    ))}
                    <Label x={PAD_LEFT} y={HEIGHT - 8} className="text-muted">
                        {periodStart.format('MMM D')}
                    </Label>
                    <Label x={WIDTH - PAD_X} y={HEIGHT - 8} anchor="end" className="text-muted">
                        {periodEnd.format('MMM D')}
                    </Label>
                    {limitY !== null && (
                        <Label x={PAD_LEFT + 4} y={limitY - 8} className="font-semibold text-danger">
                            Monthly limit · {formatCreditNumber(cap ?? 0)}
                        </Label>
                    )}
                    {showFreeLine && freeY !== null && (
                        <Label x={WIDTH - PAD_X} y={freeY - 8} anchor="end" className="font-semibold text-muted">
                            Free credits · {formatCreditNumber(freeCredits)}
                        </Label>
                    )}
                    {crossing && (
                        <Label
                            x={crossingLabelRight ? crossing.x + 8 : crossing.x - 8}
                            y={crossing.y - 8}
                            anchor={crossingLabelRight ? 'start' : 'end'}
                            className="font-semibold text-danger"
                        >
                            Limit · {crossingDate}
                        </Label>
                    )}
                    {!crossing && (
                        <Label x={end.x - 8} y={endLabelY} anchor="end" className="font-semibold text-muted">
                            {projectionLabel}
                        </Label>
                    )}
                    <Label
                        x={todayLabelX}
                        y={todayLabelY}
                        anchor={todayLabelLeft ? 'end' : 'start'}
                        className="font-semibold"
                        style={{ color: 'currentColor' }}
                    >
                        Today · {formatCreditNumber(spentTotal)}
                    </Label>
                </div>
            </div>
            {caption && <p className="m-0 text-xs text-danger">{caption}</p>}
        </div>
    )
}

// Props are loader and selector outputs, so a scanner toggle re-rendering the tab need not redraw the chart.
export const SpendTrajectoryChart = memo(SpendTrajectoryChartInner)
