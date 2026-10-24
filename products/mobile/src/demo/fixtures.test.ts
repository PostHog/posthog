import { formatActivityTime, isoDay } from '@/lib/dates'

import { DEMO_BRIEFINGS } from './briefings'
import { buildDemoFixtures, DEMO_DECISION_QUESTION } from './fixtures'
import { demoSessionLog, demoSessionRunId } from './sessionThreads'

// One anchor per weekday at 3 PM local, so "Today" and every weekday label are exercised.
const ANCHORS = [4, 5, 6, 7, 8, 9, 10].map((day) => new Date(2026, 9, day, 15, 0))

describe('demo fixtures', () => {
    test.each(ANCHORS.map((anchor) => [anchor.toDateString(), anchor]))(
        'prototype activity times round-trip on %s',
        (_label, anchor) => {
            const fixtures = buildDemoFixtures(anchor)
            const rendered = fixtures.list.flatMap(({ report }) =>
                report.activity.map((event) => formatActivityTime(event.at, anchor))
            )
            const expected = DEMO_BRIEFINGS.flatMap((briefing) => briefing.activity.map(([, when]) => when))
            expect(rendered).toEqual(expected)
        }
    )

    test('every inbox row opens a report with a complete detail view', () => {
        const fixtures = buildDemoFixtures(ANCHORS[0] as Date)
        expect(fixtures.list).toHaveLength(14)
        for (const { item, report } of fixtures.list) {
            expect(fixtures.byId[item.reportId]?.report).toBe(report)
            expect(report.title).toBe(item.title)
            expect(report.headline.rest).not.toBe('')
            expect(report.facts.length).toBeGreaterThan(0)
            expect(report.prompt).not.toBe('')
            expect(report.summary).toContain('## Problem')
            expect(report.signals.length).toBeGreaterThanOrEqual(2)
            const signalTimes = report.signals.map((signal) => Date.parse(signal.at))
            expect(signalTimes).toEqual([...signalTimes].sort((a, b) => b - a))
            if (report.task) {
                expect(demoSessionLog(report.task.taskId)?.title).toBe(report.title)
                expect(demoSessionRunId(report.task.taskId)).toBe(report.task.runId)
            }
            const observation = report.observation
            if (observation?.data.kind !== 'static') {
                throw new Error(`${report.id} has no static observation`)
            }
            const { points } = observation.data.series
            expect(points).toHaveLength(14)
            expect(points[13]?.at).toBe(isoDay(ANCHORS[0] as Date))
            expect(points.every((point) => Number.isFinite(point.value))).toBe(true)
            for (const chart of report.charts) {
                expect(chart.data === undefined || chart.data.kind === 'static').toBe(true)
            }
        }
        const reports = fixtures.list.map(({ report }) => report)
        expect(reports.filter((report) => report.supportingMetrics.length >= 2).length).toBeGreaterThanOrEqual(4)
        expect(reports.filter((report) => report.charts.some((chart) => chart.data)).length).toBeGreaterThanOrEqual(2)
        expect(reports.filter((report) => report.charts.some((chart) => !chart.data)).length).toBeGreaterThanOrEqual(2)
        const waiting = fixtures.list.filter(({ item }) => item.needsInput)
        expect(waiting.map(({ report }) => report.task?.pendingDecision)).toEqual([DEMO_DECISION_QUESTION])
    })
})
