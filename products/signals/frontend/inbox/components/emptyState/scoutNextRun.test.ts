import { scoutNextRun } from './scoutNextRun'

describe('scoutNextRun', () => {
    test.each([
        {
            name: 'rolling interval',
            scout: {
                last_run_at: '2026-06-10T23:30:00Z',
                run_cron_schedule: null,
                run_interval_minutes: 60,
            },
            timezone: 'UTC',
            currentDate: new Date('2026-06-11T00:00:00Z'),
            expected: '2026-06-11T00:30:00.000Z',
        },
        {
            name: 'cron schedule in the project timezone',
            scout: {
                last_run_at: null,
                run_cron_schedule: '0 9 * * *',
                run_interval_minutes: 1440,
            },
            timezone: 'America/New_York',
            currentDate: new Date('2026-06-11T12:00:00Z'),
            expected: '2026-06-11T13:00:00.000Z',
        },
        {
            name: 'overdue interval',
            scout: {
                last_run_at: '2026-06-10T20:00:00Z',
                run_cron_schedule: null,
                run_interval_minutes: 60,
            },
            timezone: 'UTC',
            currentDate: new Date('2026-06-11T00:00:00Z'),
            expected: null,
        },
        {
            name: 'overdue cron schedule',
            scout: {
                last_run_at: '2026-06-10T13:00:00Z',
                run_cron_schedule: '0 9 * * *',
                run_interval_minutes: 1440,
            },
            timezone: 'America/New_York',
            currentDate: new Date('2026-06-11T14:00:00Z'),
            expected: null,
        },
    ])('$name', ({ scout, timezone, currentDate, expected }) => {
        expect(scoutNextRun(scout, timezone, currentDate)?.toISOString() ?? null).toBe(expected)
    })
})
