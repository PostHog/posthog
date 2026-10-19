import { dayjs } from 'lib/dayjs'

import { TOOL_HEALTH_REPORT, weeklyReportPayload } from './recurringReportDefinitions'

describe('recurringReportDefinitions', () => {
    // The server evaluates byweekday in UTC against start_date, so the weekday must come from the UTC
    // instant of the first delivery. The +13:00 row is the one where the local and UTC weekdays differ.
    it.each([
        ['2026-10-12T08:00:00+00:00', 0, '2026-10-13T09:00:00.000Z', 'tuesday'],
        ['2026-10-18T23:30:00+00:00', 0, '2026-10-19T09:00:00.000Z', 'monday'],
        ['2026-10-31T10:00:00+00:00', 0, '2026-11-01T09:00:00.000Z', 'sunday'],
        ['2026-10-12T20:00:00-08:00', -8, '2026-10-13T17:00:00.000Z', 'tuesday'],
        ['2026-10-12T20:00:00+13:00', 13, '2026-10-12T20:00:00.000Z', 'monday'],
    ])('schedules %s (offset %s) for %s on %s', (now, offsetHours, startDate, weekday) => {
        const payload = weeklyReportPayload(
            TOOL_HEALTH_REPORT,
            'me@example.com',
            dayjs(now).utcOffset(offsetHours * 60)
        )

        expect(payload).toMatchObject({ start_date: startDate, byweekday: [weekday] })
    })

    it('emails the template weekly with no immediate send', () => {
        const payload = weeklyReportPayload(TOOL_HEALTH_REPORT, 'me@example.com', dayjs('2026-10-12T08:00:00Z'))

        expect(payload).toEqual({
            title: 'MCP tool health',
            prompt: TOOL_HEALTH_REPORT.prompt,
            ai_prompt_config: { window: { mode: 'since_last_sent' } },
            target_type: 'email',
            target_value: 'me@example.com',
            frequency: 'weekly',
            interval: 1,
            byweekday: ['tuesday'],
            start_date: '2026-10-13T09:00:00.000Z',
            send_test_now: false,
        })
    })
})
