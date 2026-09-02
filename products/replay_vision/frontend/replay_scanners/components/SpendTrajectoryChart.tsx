import { dayjs } from 'lib/dayjs'

import type { VisionQuotaApi } from '../../generated/api.schemas'
import { formatCreditCount } from '../../utils/credits'
import type { SpendSeries } from '../visionUsageLogic'

const WIDTH = 640
const HEIGHT = 200
const PAD_LEFT = 34
const PAD_X = 8
const TOP = 34
const BASE = HEIGHT - 20
const LABEL_CLEARANCE = 12
const FONT = 6.5
const ABOVE = -6
const BELOW = 11

interface SpendTrajectoryChartProps {
    quota: VisionQuotaApi
    series: SpendSeries
    /** Projected period-end demand in credits, unclamped; the chart pauses the drawn line at the limit. */
    projectedTotal: number
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

/**
 * Cumulative spend for the period against the limit: solid line to today, dashed projection to the
 * period end, dashed line where the limit sits. Spend pauses at the limit, so the drawn projection
 * never exceeds it: when demand crosses, the line flattens at the crossing and the crossing carries
 * the date. Percentages stay off the chart.
 */
export function SpendTrajectoryChart({
    quota,
    series,
    projectedTotal,
    statusVar,
}: SpendTrajectoryChartProps): JSX.Element {
    const periodStart = dayjs(quota.period_start)
    const periodEnd = dayjs(quota.period_end)
    const periodDays = Math.max(periodEnd.diff(periodStart, 'day'), 1)
    const todayDay = Math.min(Math.max(dayjs().diff(periodStart, 'day', true), 0), periodDays)

    const cumulative: number[] = []
    series.credits.reduce((sum, daily, i) => {
        cumulative[i] = sum + daily
        return cumulative[i]
    }, 0)
    const spentTotal = cumulative.length > 0 ? cumulative[cumulative.length - 1] : quota.credits_used

    const limit = quota.credit_limit
    // Spend stops at the limit, so the drawn end never exceeds it; demand only decides the slope.
    const endValue = limit !== null && limit > 0 ? Math.min(projectedTotal, limit) : projectedTotal
    // The free allocation gets its own quieter line, unless it IS the limit (the free plan).
    const freeCredits = quota.free_monthly_credits
    const drawFreeLine = freeCredits > 0 && (limit === null || freeCredits < limit)
    const maxValue = Math.max(limit ?? 0, endValue, spentTotal, drawFreeLine ? freeCredits : 0, 1)
    const xForDay = (day: number): number => PAD_LEFT + (day / periodDays) * (WIDTH - PAD_LEFT - PAD_X)
    const yForCredits = (credits: number): number => BASE - (credits / maxValue) * (BASE - TOP)

    const spentPoints: Point[] =
        cumulative.length > 0
            ? cumulative.map((value, i) => ({ x: xForDay(Math.min(i + 1, todayDay)), y: yForCredits(value) }))
            : [{ x: xForDay(todayDay), y: yForCredits(spentTotal) }]
    const origin: Point = { x: xForDay(0), y: yForCredits(0) }
    const today: Point = spentPoints[spentPoints.length - 1]
    // A day-old period leaves no width to draw a line in; a lone dot reads better than a vertical stroke.
    const drawSpentLine = todayDay >= 1.5
    const end: Point = { x: xForDay(periodDays), y: yForCredits(endValue) }

    // Where the straight demand line meets the limit, in period days; null when it never does.
    let crossing: Point | null = null
    let crossingDate: string | null = null
    if (limit !== null && limit > 0 && spentTotal < limit && projectedTotal > limit) {
        const t = (limit - spentTotal) / (projectedTotal - spentTotal)
        const crossDay = todayDay + t * (periodDays - todayDay)
        crossing = { x: xForDay(crossDay), y: yForCredits(limit) }
        crossingDate = periodStart.add(crossDay, 'day').format('MMM D')
    }
    const pausedAtLimit = limit !== null && limit > 0 && spentTotal >= limit

    // Round tick steps (1/2/2.5/5 per decade) so the y labels land on friendly numbers.
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
    const projectionLabel = `${periodEnd.format('MMM D')} · ~${Math.round(endValue).toLocaleString('en-US')}`
    const limitY = limit !== null && limit > 0 ? yForCredits(limit) : null
    const freeY = drawFreeLine ? yForCredits(freeCredits) : null
    // Two dotted reference lines an em apart read as one; drop the free one when they nearly touch.
    const showFreeLine = freeY !== null && (limitY === null || Math.abs(freeY - limitY) >= LABEL_CLEARANCE)

    // Labels prefer sitting above their anchor; they flip below when a reference line runs through that spot.
    const referenceYs = [limitY, freeY].filter((y): y is number => y !== null)
    const labelY = (anchorY: number): number => {
        const above = Math.max(anchorY + ABOVE, 10)
        if (
            referenceYs.every((y) => Math.abs(above - y) >= LABEL_CLEARANCE && Math.abs(anchorY - y) >= LABEL_CLEARANCE)
        ) {
            return above
        }
        return Math.min(anchorY + BELOW, BASE - 4)
    }
    // Every line leaves the today dot upward or to the right, so a label sitting level on its left
    // is the one spot nothing crosses. Near the left edge it flips to the right instead.
    const todayLabelLeft = today.x >= 60
    const todayLabelX = todayLabelLeft ? today.x - 9 : today.x + 9
    // On the right of the dot the projection climbs through the space above, so the label sits below;
    // it only moves back above when a reference line already occupies the spot below.
    const belowY = Math.min(today.y + BELOW, BASE - 4)
    const rightSideY = referenceYs.every((y) => Math.abs(belowY - y) >= LABEL_CLEARANCE) ? belowY : today.y - 16
    // A side label level with a reference line sits on its dashes; lift it just above instead.
    const sideY = referenceYs.some((y) => Math.abs(today.y - y) < 8) ? today.y - 5 : today.y + 2.5
    const todayLabelY = todayLabelLeft ? sideY : rightSideY
    const endLabelY = labelY(end.y)

    return (
        <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            style={{ width: '100%', height: 'auto', display: 'block' }}
            role="img"
            aria-label={`Cumulative spend this period: ${formatCreditCount(spentTotal)} so far, projected ${formatCreditCount(endValue)} by ${periodEnd.format('MMMM D')}${limit !== null ? `, limit ${formatCreditCount(limit)}` : ''}`}
        >
            {yTicks.map((v) => (
                <g key={v}>
                    <line
                        x1={PAD_LEFT}
                        y1={yForCredits(v)}
                        x2={WIDTH - PAD_X}
                        y2={yForCredits(v)}
                        stroke="var(--border)"
                        strokeWidth={0.5}
                        opacity={0.6}
                    />
                    <text x={PAD_LEFT - 4} y={yForCredits(v) + 2} fontSize={FONT} fill={mutedVar} textAnchor="end">
                        {v >= 1000 ? `${Math.round(v / 100) / 10}k` : Math.round(v)}
                    </text>
                </g>
            ))}
            <text x={PAD_LEFT - 4} y={BASE + 2} fontSize={FONT} fill={mutedVar} textAnchor="end">
                0
            </text>
            <line x1={PAD_LEFT} y1={TOP - 14} x2={PAD_LEFT} y2={BASE} stroke="var(--border)" strokeWidth={1} />
            {xTicks.map((day) => (
                <g key={day}>
                    <line
                        x1={xForDay(day)}
                        y1={BASE}
                        x2={xForDay(day)}
                        y2={BASE + 3}
                        stroke="var(--border)"
                        strokeWidth={1}
                    />
                    <text x={xForDay(day)} y={HEIGHT - 4} fontSize={FONT} fill={mutedVar} textAnchor="middle">
                        {periodStart.add(day, 'day').format('MMM D')}
                    </text>
                </g>
            ))}
            {limitY !== null && (
                <>
                    <line
                        x1={PAD_LEFT}
                        y1={limitY}
                        x2={WIDTH - PAD_X}
                        y2={limitY}
                        stroke={dangerVar}
                        strokeWidth={1}
                        strokeDasharray="2 3"
                    />
                    <text x={PAD_LEFT + 4} y={limitY - 6} fontSize={FONT} fontWeight={600} fill={dangerVar}>
                        Monthly limit · {Math.round(limit ?? 0).toLocaleString('en-US')}
                    </text>
                </>
            )}
            {showFreeLine && freeY !== null && (
                <>
                    <line
                        x1={PAD_LEFT}
                        y1={freeY}
                        x2={WIDTH - PAD_X}
                        y2={freeY}
                        stroke={mutedVar}
                        strokeWidth={1}
                        strokeDasharray="2 3"
                        opacity={0.7}
                    />
                    <text
                        x={WIDTH - PAD_X}
                        y={freeY + BELOW}
                        fontSize={FONT}
                        fontWeight={600}
                        fill={mutedVar}
                        textAnchor="end"
                    >
                        Free credits · {Math.round(freeCredits).toLocaleString('en-US')}
                    </text>
                </>
            )}
            <line x1={PAD_LEFT} y1={BASE} x2={WIDTH - PAD_X} y2={BASE} stroke="var(--border)" strokeWidth={1} />
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
                        strokeWidth={1.5}
                        strokeDasharray="4 4"
                        strokeLinecap="round"
                    />
                    <polyline
                        points={pointsAttr([crossing, { x: end.x, y: crossing.y }])}
                        fill="none"
                        stroke={dangerVar}
                        strokeWidth={1.5}
                        strokeDasharray="2 5"
                        strokeLinecap="round"
                        opacity={0.7}
                    />
                    <circle cx={crossing.x} cy={crossing.y} r={3} fill={dangerVar} />
                    <text
                        x={Math.min(Math.max(crossing.x + 8, 140), WIDTH - 230)}
                        y={Math.min(crossing.y + BELOW, BASE - 6)}
                        fontSize={FONT}
                        fontWeight={600}
                        fill={dangerVar}
                    >
                        Hits the limit around {crossingDate}. Scanning pauses until {periodEnd.format('MMM D')}.
                    </text>
                </>
            ) : (
                <>
                    <polyline
                        points={pointsAttr([today, end])}
                        fill="none"
                        stroke={pausedAtLimit ? dangerVar : statusVar}
                        strokeWidth={1.5}
                        strokeDasharray="4 4"
                        strokeLinecap="round"
                    />
                    <circle cx={end.x} cy={end.y} r={3} fill={pausedAtLimit ? dangerVar : statusVar} />
                    <text x={end.x - 8} y={endLabelY} fontSize={FONT} fontWeight={600} fill={mutedVar} textAnchor="end">
                        {projectionLabel}
                    </text>
                </>
            )}
            <circle cx={today.x} cy={today.y} r={3} fill="currentColor" />
            <text
                x={todayLabelX}
                y={todayLabelY}
                fontSize={FONT}
                fontWeight={600}
                fill="currentColor"
                textAnchor={todayLabelLeft ? 'end' : 'start'}
            >
                Today · {Math.round(spentTotal).toLocaleString('en-US')}
            </text>
            <text x={PAD_LEFT} y={HEIGHT - 4} fontSize={FONT} fill={mutedVar}>
                {periodStart.format('MMM D')}
            </text>
            <text x={WIDTH - PAD_X} y={HEIGHT - 4} fontSize={FONT} fill={mutedVar} textAnchor="end">
                {periodEnd.format('MMM D')}
            </text>
        </svg>
    )
}
