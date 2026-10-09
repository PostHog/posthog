import { formatActivityTime } from '@/lib/dates'

import { DEMO_BRIEFINGS } from './briefings'
import { buildDemoFixtures, DEMO_DECISION_QUESTION } from './fixtures'

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
        expect(fixtures.list).toHaveLength(7)
        for (const { item, report } of fixtures.list) {
            expect(fixtures.byId[item.reportId]?.report).toBe(report)
            expect(report.title).toBe(item.title)
            expect(report.headline.rest).not.toBe('')
            expect(report.facts.length).toBeGreaterThan(0)
            expect(report.metric?.bars).toHaveLength(14)
            expect(report.prompt).not.toBe('')
        }
        const waiting = fixtures.list.filter(({ item }) => item.needsInput)
        expect(waiting.map(({ report }) => report.task?.pendingDecision)).toEqual([DEMO_DECISION_QUESTION])
    })
})
