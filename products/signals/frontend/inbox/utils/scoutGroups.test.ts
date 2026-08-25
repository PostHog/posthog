import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { SignalScoutRunSummary } from '../types'
import { nextRunAt, scoutCadenceLabel, scoutGroup, ScoutGroupKey, scoutSubtitle } from './scoutGroups'
import { computeScoutRollups, ScoutRollup } from './scoutRunsWindow'

const NOW = new Date('2026-06-27T22:00:00Z')

function makeConfig(overrides: Partial<SignalScoutConfig> = {}): SignalScoutConfig {
    return {
        id: 'config-1',
        skill_name: 'signals-scout-apm',
        description: 'Watches latency and throughput.',
        scout_origin: 'canonical',
        enabled: true,
        status: 'active',
        pause_reason: null,
        emit: true,
        run_interval_minutes: 60,
        run_cron_schedule: null,
        output_destinations: {},
        structured_output_schema: null,
        network_access: 'trusted',
        model: null,
        last_run_at: '2026-06-27T21:30:00Z',
        consecutive_failure_count: 0,
        status_changed_at: null,
        auto_pause_exempt: false,
        tags: [],
        created_at: '2026-01-01T00:00:00Z',
        ...overrides,
    } as SignalScoutConfig
}

function makeRun(overrides: Partial<SignalScoutRunSummary> = {}): SignalScoutRunSummary {
    return {
        run_id: 'run-1',
        skill_name: 'signals-scout-apm',
        skill_version: 1,
        status: 'completed',
        metadata: {},
        created_at: '2026-06-27T21:00:00Z',
        started_at: '2026-06-27T21:00:00Z',
        completed_at: '2026-06-27T21:02:00Z',
        summary: '',
        emitted_count: 0,
        emitted_finding_ids: [],
        emitted_report_ids: [],
        edited_report_ids: [],
        ...overrides,
    }
}

function rollupFor(runs: SignalScoutRunSummary[]): ScoutRollup | undefined {
    return computeScoutRollups(runs).get('signals-scout-apm')
}

describe('scoutGroups', () => {
    describe('scoutGroup', () => {
        it.each<[string, Partial<SignalScoutConfig>, SignalScoutRunSummary[], ScoutGroupKey]>([
            [
                'a system pause outranks everything else',
                { status: 'paused_by_system', pause_reason: 'repeated_failures', enabled: false },
                [],
                'needs_you',
            ],
            [
                'a warning still needs a person even though it keeps running',
                { status: 'pending_pause', pause_reason: 'ignored' },
                [makeRun({ emitted_report_ids: ['r-1'] })],
                'needs_you',
            ],
            ['a human pause is off, not trouble', { status: 'paused_by_user', enabled: false }, [], 'off'],
            ['dry run beats output — it files nothing', { emit: false }, [makeRun({ emitted_count: 3 })], 'dry_run'],
            [
                'a new scout is not judged on its output yet',
                { created_at: '2026-06-25T00:00:00Z' },
                [makeRun({ emitted_count: 1 })],
                'settling_in',
            ],
            ['reports authored count as producing', {}, [makeRun({ emitted_report_ids: ['r-1'] })], 'working'],
            ['edited reports count as producing', {}, [makeRun({ edited_report_ids: ['r-2'] })], 'working'],
            ['findings count as producing', {}, [makeRun({ emitted_count: 2 })], 'working'],
            ['running with no output is watching, not trouble', {}, [makeRun()], 'watching'],
            ['no runs at all is still watching', {}, [], 'watching'],
        ])('%s', (_name, overrides, runs, expected) => {
            expect(scoutGroup(makeConfig(overrides), rollupFor(runs), NOW)).toEqual(expected)
        })

        it('restarts the settling-in window when a human re-enables a scout', () => {
            const reEnabled = makeConfig({
                created_at: '2026-01-01T00:00:00Z',
                status_changed_at: '2026-06-24T00:00:00Z',
            })
            expect(scoutGroup(reEnabled, rollupFor([]), NOW)).toEqual('settling_in')
        })
    })

    describe('scoutSubtitle', () => {
        it('names the failure streak so a paused scout says why', () => {
            const config = makeConfig({
                status: 'paused_by_system',
                pause_reason: 'repeated_failures',
                consecutive_failure_count: 4,
                enabled: false,
            })
            expect(scoutSubtitle(config, undefined, NOW)).toEqual({
                text: 'Paused itself — 4 runs in a row failed',
                tone: 'danger',
            })
        })

        it.each<[string, Partial<SignalScoutConfig>, string]>([
            [
                'an ignored pause blames consumption, not silence',
                { status: 'paused_by_system', pause_reason: 'ignored', enabled: false },
                'Paused — nobody acted on its reports',
            ],
            [
                'a no-output warning asks a person to look',
                { status: 'pending_pause', pause_reason: 'no_output' },
                'Warned — nothing surfaced in the last two weeks',
            ],
            ['a dry run says it files nothing', { emit: false }, 'Runs and investigates, but files nothing'],
        ])('%s', (_name, overrides, expected) => {
            expect(scoutSubtitle(makeConfig(overrides), undefined, NOW)?.text).toEqual(expected)
        })

        it('prefers what the last run checked over the scout description', () => {
            const rollup = rollupFor([
                makeRun({ summary: 'Swept 40 event series against the 14-day baseline. All inside range.' }),
            ])
            expect(scoutSubtitle(makeConfig(), rollup, NOW)?.text).toEqual(
                'Swept 40 event series against the 14-day baseline. All inside range.'
            )
        })

        it('falls back to the description when no run has closed out', () => {
            expect(scoutSubtitle(makeConfig(), rollupFor([]), NOW)?.text).toEqual('Watches latency and throughput.')
        })

        // Both anchor the settling-in window; only a fresh scout was actually created recently.
        it.each([
            ['a fresh scout', { created_at: '2026-06-26T22:00:00Z', status_changed_at: null }, 'Created '],
            [
                'a re-enabled scout',
                { created_at: '2026-01-01T00:00:00Z', status_changed_at: '2026-06-26T22:00:00Z' },
                'Turned on ',
            ],
        ])('says how %s entered the settling-in window', (_name, overrides, verb) => {
            // `fromNow()` reads the wall clock, so only the verb is stable enough to pin.
            expect(scoutSubtitle(makeConfig(overrides), rollupFor([]), NOW)?.text.startsWith(verb)).toBe(true)
        })
    })

    describe('scoutCadenceLabel', () => {
        it.each<[string, Partial<SignalScoutConfig>, string]>([
            ['a rolling interval', { run_interval_minutes: 60 }, 'hourly'],
            ['a plain daily cron keeps the friendlier phrasing', { run_cron_schedule: '0 9 * * *' }, 'daily at 09:00'],
            [
                'a richer cron is spelled out rather than shown raw',
                { run_cron_schedule: '35 8 * * 1-5' },
                'at 08:35 am, monday through friday',
            ],
        ])('%s', (_name, overrides, expected) => {
            expect(scoutCadenceLabel(makeConfig(overrides))).toEqual(expected)
        })
    })

    describe('nextRunAt', () => {
        it('adds the rolling interval to the last run', () => {
            expect(nextRunAt(makeConfig({ run_interval_minutes: 60 }), 'UTC', NOW)).toEqual(
                new Date('2026-06-27T22:30:00Z')
            )
        })

        it.each<[string, Partial<SignalScoutConfig>]>([
            ['a scout that has never run', { last_run_at: null }],
            ['a disabled scout', { enabled: false }],
            ['an expression that does not parse', { run_cron_schedule: 'not a cron' }],
        ])('says nothing for %s', (_name, overrides) => {
            expect(nextRunAt(makeConfig(overrides), 'UTC', NOW)).toBeNull()
        })

        it('resolves a multi-slot cron rather than giving up on it', () => {
            // 09:00 and 17:00 daily; NOW is 22:00, so the next slot is tomorrow morning.
            const config = makeConfig({ run_cron_schedule: '0 9,17 * * *' })
            expect(nextRunAt(config, 'UTC', NOW)).toEqual(new Date('2026-06-28T09:00:00Z'))
        })

        it('evaluates a cron in the project timezone, not the browser one', () => {
            const config = makeConfig({ run_cron_schedule: '0 9 * * *' })
            // 09:00 in New York on Jun 28 is 13:00 UTC (EDT, UTC-4).
            expect(nextRunAt(config, 'America/New_York', NOW)).toEqual(new Date('2026-06-28T13:00:00Z'))
        })

        it('rolls a daily cron to tomorrow once today’s slot has passed', () => {
            const config = makeConfig({ run_cron_schedule: '0 9 * * *' })
            expect(nextRunAt(config, 'UTC', NOW)).toEqual(new Date('2026-06-28T09:00:00Z'))
        })
    })
})
