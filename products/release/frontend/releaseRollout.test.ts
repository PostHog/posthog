import { dayjs } from 'lib/dayjs'

import type {
    ActivityLogEntryApi,
    FeatureFlagApi,
    ScheduledChangeApi,
} from 'products/feature_flags/frontend/generated/api.schemas'

import { rolloutSteps } from './releaseRollout'

const TODAY = dayjs('2026-11-12T12:00:00Z')
const HORIZON = dayjs('2026-12-01T00:00:00Z')

const groups = (rollout: number): { groups: { properties: never[]; rollout_percentage: number }[] } => ({
    groups: [{ properties: [], rollout_percentage: rollout }],
})

const flag = (rollout: number, active = true): FeatureFlagApi =>
    ({
        id: 7,
        key: 'checkout',
        active,
        created_at: '2026-11-01T00:00:00Z',
        filters: groups(rollout),
    }) as unknown as FeatureFlagApi

const update = (at: string, changes: { field: string; before: unknown; after: unknown }[]): ActivityLogEntryApi =>
    ({ activity: 'updated', created_at: at, detail: { changes } }) as unknown as ActivityLogEntryApi

const schedule = (at: string, payload: Record<string, unknown>, executed = false): ScheduledChangeApi =>
    ({
        record_id: '7',
        scheduled_at: at,
        executed_at: executed ? at : null,
        payload,
    }) as unknown as ScheduledChangeApi

const summary = (steps: ReturnType<typeof rolloutSteps>): [string, string, boolean][] =>
    steps.map((step) => [step.from.slice(0, 10), step.label, !!step.upcoming])

describe('rolloutSteps', () => {
    test.each([
        {
            name: 'starts from the state before the first change, not the current one',
            current: flag(50),
            activity: [
                update('2026-11-04T00:00:00Z', [{ field: 'filters', before: groups(10), after: groups(25) }]),
                update('2026-11-08T00:00:00Z', [{ field: 'filters', before: groups(25), after: groups(50) }]),
            ],
            scheduled: [],
            expected: [
                ['2026-11-01', '10%', false],
                ['2026-11-04', '25%', false],
                ['2026-11-08', '50%', false],
            ],
        },
        {
            name: 'turning the flag off reads as nobody getting it',
            current: flag(30, false),
            activity: [update('2026-11-05T00:00:00Z', [{ field: 'active', before: true, after: false }])],
            scheduled: [],
            expected: [
                ['2026-11-01', '30%', false],
                ['2026-11-05', 'Off', false],
            ],
        },
        {
            name: 'merges changes that leave the audience the same',
            current: flag(100),
            activity: [update('2026-11-03T00:00:00Z', [{ field: 'filters', before: groups(100), after: groups(100) }])],
            scheduled: [],
            expected: [['2026-11-01', 'Everyone', false]],
        },
        {
            name: 'adds pending scheduled changes as upcoming steps, in date order, and skips executed ones',
            current: flag(50),
            activity: [],
            scheduled: [
                schedule('2026-11-18T00:00:00Z', { operation: 'add_release_condition', value: groups(100) }),
                schedule('2026-11-14T00:00:00Z', { operation: 'add_release_condition', value: groups(75) }),
                schedule('2026-11-10T00:00:00Z', { operation: 'add_release_condition', value: groups(60) }, true),
            ],
            expected: [
                ['2026-11-01', '50%', false],
                ['2026-11-14', '75%', true],
                ['2026-11-18', 'Everyone', true],
            ],
        },
    ])('$name', ({ current, activity, scheduled, expected }) => {
        expect(summary(rolloutSteps(current, activity, scheduled, TODAY, HORIZON))).toEqual(expected)
    })

    it('ends the current step today when the next one is only scheduled', () => {
        const steps = rolloutSteps(
            flag(50),
            [],
            [schedule('2026-11-14T00:00:00Z', { operation: 'add_release_condition', value: groups(75) })],
            TODAY,
            HORIZON
        )
        expect(steps[0].to).toBe(TODAY.toISOString())
        expect(steps[1].to).toBe(HORIZON.toISOString())
    })
})
