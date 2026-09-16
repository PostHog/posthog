import { dayjs } from 'lib/dayjs'

import { makeQuota } from '../../utils/quotaTestUtils'
import type { SpendSeries } from '../visionUsageLogic'
import {
    PROJECTED_SERIES_KEY,
    type SpendCrossing,
    type SpendMarker,
    type SpendTrajectory,
    buildProjectedSeries,
    buildSpendMarkers,
    buildSpendPeriodAxis,
    buildSpendTrajectory,
    buildSpentSeries,
    resolveFreeCreditsLine,
    resolveSpendCrossing,
} from './spendTrajectoryTransforms'

const PERIOD_START = '2026-05-01T00:00:00Z'
const PERIOD_END = '2026-06-01T00:00:00Z'
const NOW = dayjs.utc('2026-05-12T10:00:00Z')
const AXIS = buildSpendPeriodAxis(PERIOD_START, PERIOD_END, NOW)
const TODAY_INDEX = 11
const END_INDEX = 31
const STATUS = 'var(--success)'
const DANGER = 'var(--danger)'
const CROSSING: SpendCrossing = { index: 19, value: 10_000, date: dayjs.utc('2026-05-20T06:00:00Z') }

function ledger(total: number, days: number): SpendSeries {
    return Array.from({ length: days }, (_, i) => ({
        date: dayjs.utc(PERIOD_START).add(i, 'day').format('YYYY-MM-DD'),
        credits: Math.round(total / days),
    }))
}

function markerByKey(markers: SpendMarker[], key: SpendMarker['key']): SpendMarker {
    const marker = markers.find((m) => m.key === key)
    expect(marker).not.toBeUndefined()
    return marker as SpendMarker
}

function projectedSeries(trajectory: SpendTrajectory): { data: number[]; color?: string } {
    const series = trajectory.series.find((s) => s.key === PROJECTED_SERIES_KEY)
    expect(series).not.toBeUndefined()
    return { data: series!.data as number[], color: series!.color }
}

describe('spendTrajectoryTransforms', () => {
    describe('buildSpendPeriodAxis', () => {
        it('lays one UTC day per label across the period and places today on its UTC day', () => {
            expect(AXIS.labels).toHaveLength(END_INDEX + 1)
            expect(AXIS.labels[0]).toBe('2026-05-01')
            expect(AXIS.labels[END_INDEX]).toBe('2026-06-01')
            expect(AXIS.todayIndex).toBe(TODAY_INDEX)
            expect(AXIS.endIndex).toBe(END_INDEX)
        })

        it('clamps today into the period', () => {
            expect(buildSpendPeriodAxis(PERIOD_START, PERIOD_END, dayjs.utc('2026-07-01')).todayIndex).toBe(END_INDEX)
            expect(buildSpendPeriodAxis(PERIOD_START, PERIOD_END, dayjs.utc('2026-04-01')).todayIndex).toBe(0)
        })
    })

    describe('buildSpentSeries', () => {
        it('accumulates the ledger up to today and leaves the rest empty', () => {
            const spent = buildSpentSeries(ledger(4_000, 4), 4_000, AXIS)
            expect(spent[0]).toBe(1_000)
            expect(spent[3]).toBe(4_000)
            expect(spent[TODAY_INDEX]).toBe(4_000)
            expect(spent[TODAY_INDEX + 1]).toBeNaN()
        })

        it('pins today to the quota total when the ledger runs ahead', () => {
            const spent = buildSpentSeries(ledger(4_400, 4), 4_000, AXIS)
            expect(spent[2]).toBe(3_300)
            expect(spent[3]).toBe(4_000)
            expect(spent[TODAY_INDEX]).toBe(4_000)
        })

        it('draws only today when there is no ledger', () => {
            const spent = buildSpentSeries([], 4_000, AXIS)
            expect(spent[0]).toBeNaN()
            expect(spent[TODAY_INDEX]).toBe(4_000)
        })
    })

    describe('resolveSpendCrossing', () => {
        it('lands the crossing on the UTC day of the verdict date', () => {
            const crossing = resolveSpendCrossing(dayjs.utc('2026-05-20T06:00:00Z'), 10_000, 4_000, AXIS)
            expect(crossing).not.toBeNull()
            expect(crossing!.index).toBe(19)
            expect(crossing!.value).toBe(10_000)
            expect(crossing!.date.format('YYYY-MM-DD')).toBe('2026-05-20')
        })

        it.each([
            ['there is no limit', dayjs.utc('2026-05-20'), null, 4_000],
            ['spend is already at the limit', dayjs.utc('2026-05-20'), 10_000, 10_000],
            ['the crossing is today', dayjs.utc('2026-05-12T18:00:00Z'), 10_000, 4_000],
            ['the crossing is after the period', dayjs.utc('2026-06-02'), 10_000, 4_000],
        ])('returns null when %s', (_, capReachDate, cap, spentTotal) => {
            expect(resolveSpendCrossing(capReachDate, cap, spentTotal, AXIS)).toBeNull()
        })
    })

    describe('buildProjectedSeries', () => {
        it('runs from today to the crossing and stops there', () => {
            const projected = buildProjectedSeries(4_000, 10_000, CROSSING, AXIS)
            expect(projected[TODAY_INDEX - 1]).toBeNaN()
            expect(projected[TODAY_INDEX]).toBe(4_000)
            expect(projected[19]).toBe(10_000)
            expect(projected[20]).toBeNaN()
        })

        it('runs from today to period end otherwise', () => {
            const projected = buildProjectedSeries(4_000, 6_000, null, AXIS)
            expect(projected[TODAY_INDEX]).toBe(4_000)
            expect(projected[END_INDEX]).toBe(6_000)
        })
    })

    describe('resolveFreeCreditsLine', () => {
        it.each([
            ['it would sit on the axis', 1_000, 240_000, 240_000, null],
            ['it clears the axis and the limit', 2_500, 10_000, 10_000, 2_500],
            ['it is the limit itself', 2_500, 2_500, 2_500, null],
            ['there is no limit', 2_500, null, 6_000, 2_500],
        ])('draws the free-credits line only when %s', (_, free, cap, axisMax, expected) => {
            expect(resolveFreeCreditsLine(free, cap, axisMax)).toBe(expected)
        })
    })

    describe('buildSpendMarkers', () => {
        it('names the crossing day when demand crosses the limit', () => {
            const markers = buildSpendMarkers(4_000, 10_000, CROSSING, AXIS)
            expect(markerByKey(markers, 'today')).toMatchObject({ label: '2026-05-12', text: 'Today · 4,000' })
            expect(markerByKey(markers, 'crossing')).toMatchObject({
                label: '2026-05-20',
                value: 10_000,
                text: 'Limit · May 20',
            })
        })

        it('names the period end otherwise', () => {
            const markers = buildSpendMarkers(4_000, 6_000, null, AXIS)
            expect(markerByKey(markers, 'end')).toMatchObject({ label: '2026-06-01', text: 'Jun 1 · ~6,000' })
        })
    })

    describe('buildSpendTrajectory', () => {
        it('colours the projection danger and stops it at the crossing when demand hits the limit', () => {
            const trajectory = buildSpendTrajectory({
                quota: makeQuota({
                    period_start: PERIOD_START,
                    period_end: PERIOD_END,
                    credit_limit: 10_000,
                    credits_used: 4_000,
                }),
                dailyCredits: ledger(4_000, TODAY_INDEX + 1),
                projectedTotal: 16_000,
                capReachDate: dayjs.utc('2026-05-20T06:00:00Z'),
                statusColor: STATUS,
                dangerColor: DANGER,
                now: NOW,
            })
            const projected = projectedSeries(trajectory)
            expect(projected.color).toBe(DANGER)
            expect(projected.data[19]).toBe(10_000)
            expect(projected.data[20]).toBeNaN()
            expect(trajectory.crossing).not.toBeNull()
            expect(trajectory.crossing!.date.format('YYYY-MM-DD')).toBe('2026-05-20')
            expect(trajectory.endValue).toBe(10_000)
        })

        it('holds the projection flat at the limit once spend has reached it', () => {
            const trajectory = buildSpendTrajectory({
                quota: makeQuota({
                    period_start: PERIOD_START,
                    period_end: PERIOD_END,
                    credit_limit: 10_000,
                    credits_used: 10_000,
                }),
                dailyCredits: ledger(10_000, TODAY_INDEX + 1),
                projectedTotal: 14_000,
                capReachDate: null,
                statusColor: STATUS,
                dangerColor: DANGER,
                now: NOW,
            })
            const projected = projectedSeries(trajectory)
            expect(trajectory.pausedAtLimit).toBe(true)
            expect(projected.color).toBe(DANGER)
            expect(projected.data[TODAY_INDEX]).toBe(10_000)
            expect(projected.data[END_INDEX]).toBe(10_000)
        })

        it('runs the projection to demand in the status colour when there is no limit', () => {
            const trajectory = buildSpendTrajectory({
                quota: makeQuota({
                    period_start: PERIOD_START,
                    period_end: PERIOD_END,
                    credit_limit: null,
                    credits_used: 4_000,
                }),
                dailyCredits: ledger(4_000, TODAY_INDEX + 1),
                projectedTotal: 6_000,
                capReachDate: null,
                statusColor: STATUS,
                dangerColor: DANGER,
                now: NOW,
            })
            const projected = projectedSeries(trajectory)
            expect(trajectory.cap).toBeNull()
            expect(projected.color).toBe(STATUS)
            expect(projected.data[END_INDEX]).toBe(6_000)
            expect(markerByKey(trajectory.markers, 'end').text).toBe('Jun 1 · ~6,000')
        })
    })
})
