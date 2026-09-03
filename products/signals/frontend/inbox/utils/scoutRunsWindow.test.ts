import { pluralize } from 'lib/utils/strings'

import { SignalScoutRunSummary } from '../types'
import {
    computeFleetSummary,
    computeScoutRollups,
    deriveRunOutcome,
    mostRecentEmittedRuns,
    runMatchesFilter,
    dayTimeToWeeklyCron,
    getScoutScheduleMode,
    SCOUT_CUSTOM_CRON_SCHEDULE_MODE,
    SCOUT_DAILY_AT_SCHEDULE_MODE,
    SCOUT_WEEKLY_ON_SCHEDULE_MODE,
    ScoutRunOutcome,
    scoutCronScheduleError,
    scoutReportActivityLabel,
    weeklyCronToDayTime,
} from './scoutRunsWindow'

const NOW = new Date('2026-06-27T22:00:00Z')

function makeRun(overrides: Partial<SignalScoutRunSummary> = {}): SignalScoutRunSummary {
    return {
        run_id: 'run-1',
        skill_name: 'signals-scout-dev-report-probe',
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

describe('scoutRunsWindow report channel', () => {
    // The report channel (emit_report/edit_report) is invisible to emitted_count, so a report-authoring
    // run used to read as "quiet / 0 signals emitted". These lock in that report activity counts as output.
    describe('deriveRunOutcome', () => {
        it.each<[string, Partial<SignalScoutRunSummary>, ScoutRunOutcome]>([
            ['authored a report, no findings → reported', { emitted_report_ids: ['r-1'] }, 'reported'],
            ['only edited a report, no findings → reported', { edited_report_ids: ['r-2'] }, 'reported'],
            ['no findings and no reports → quiet', {}, 'quiet'],
            [
                'findings win over report activity → emitted',
                { emitted_count: 2, emitted_finding_ids: ['f-1', 'f-2'], emitted_report_ids: ['r-1'] },
                'emitted',
            ],
        ])('%s', (_name, overrides, expected) => {
            expect(deriveRunOutcome(makeRun(overrides), NOW)).toEqual(expected)
        })
    })

    describe('runMatchesFilter', () => {
        it('keeps a report-authoring run out of Quiet and inside Emitted', () => {
            const run = makeRun({ emitted_report_ids: ['r-1'] })
            expect(runMatchesFilter(run, 'quiet')).toBe(false)
            expect(runMatchesFilter(run, 'emitted')).toBe(true)
        })

        it('keeps a genuinely quiet run inside Quiet and out of Emitted', () => {
            const run = makeRun()
            expect(runMatchesFilter(run, 'quiet')).toBe(true)
            expect(runMatchesFilter(run, 'emitted')).toBe(false)
        })
    })

    describe('scoutReportActivityLabel', () => {
        // Expected built via `pluralize` so the count↔word non-breaking space matches without hardcoding
        // an invisible character in the literal. The ` · ` separator uses normal spaces.
        it.each<[string, Partial<SignalScoutRunSummary>, string | null]>([
            ['authored only', { emitted_report_ids: ['r-1'] }, `${pluralize(1, 'report')} authored`],
            ['edited only (pluralized)', { edited_report_ids: ['r-1', 'r-2'] }, `${pluralize(2, 'report')} edited`],
            [
                'both authored and edited',
                { emitted_report_ids: ['r-1'], edited_report_ids: ['r-2'] },
                `${pluralize(1, 'report')} authored · ${pluralize(1, 'report')} edited`,
            ],
            ['no report activity', {}, null],
        ])('%s', (_name, overrides, expected) => {
            expect(scoutReportActivityLabel(makeRun(overrides))).toEqual(expected)
        })
    })

    describe('computeScoutRollups', () => {
        it('dedupes report ids across runs into the authored/edited sets', () => {
            const skill = 'signals-scout-dev-report-probe'
            const runs = [
                makeRun({ run_id: 'run-1', skill_name: skill, emitted_report_ids: ['r-1'] }),
                // The same report is edited by a later run — must not double-count, and stays distinct
                // from the authored set.
                makeRun({ run_id: 'run-2', skill_name: skill, edited_report_ids: ['r-1'] }),
                makeRun({ run_id: 'run-3', skill_name: skill, edited_report_ids: ['r-2'] }),
            ]
            const rollup = computeScoutRollups(runs).get(skill)!
            expect([...rollup.authoredReportIds]).toEqual(['r-1'])
            expect([...rollup.editedReportIds].sort()).toEqual(['r-1', 'r-2'])
        })
    })

    describe('mostRecentEmittedRuns', () => {
        it('includes report-channel-only runs alongside emitted runs, excluding quiet ones', () => {
            // The fleet findings page fetches this set — narrowing it back to `emitted_count > 0`
            // would silently drop report-authoring runs, so their reports never get listed.
            const runs = [
                makeRun({ run_id: 'run-findings', emitted_count: 1, emitted_finding_ids: ['f-1'] }),
                makeRun({ run_id: 'run-authored', emitted_report_ids: ['r-1'] }),
                makeRun({ run_id: 'run-edited', edited_report_ids: ['r-2'] }),
                makeRun({ run_id: 'run-quiet' }),
            ]
            expect(mostRecentEmittedRuns(runs).map((run) => run.run_id)).toEqual([
                'run-findings',
                'run-authored',
                'run-edited',
            ])
        })
    })

    describe('computeFleetSummary', () => {
        it('counts a report-only run toward emit rate, matching the Emitted filter', () => {
            // Guards the divergence where the fleet emit rate counted only `emitted_count > 0` while the
            // per-scout "Emitted" chip counts report-channel output too — the two surfaces must agree.
            const rollups = computeScoutRollups([makeRun({ emitted_report_ids: ['r-1'] })])
            expect(computeFleetSummary([], rollups).emitRate).toEqual(1)
        })

        it('dedupes touched reports across scouts and channels', () => {
            // The pulse line counts distinct reports the fleet touched. Summing per-scout sets instead
            // would double-count a report authored by one scout and edited by another (r-1 below), and
            // the header would advertise more reports than the findings page lists.
            const rollups = computeScoutRollups([
                makeRun({ skill_name: 'scout-a', emitted_report_ids: ['r-1'] }),
                makeRun({ skill_name: 'scout-b', edited_report_ids: ['r-1', 'r-2'] }),
            ])
            expect(computeFleetSummary([], rollups).touchedReportCount).toEqual(2)
        })
    })
})

describe('scout schedule modes', () => {
    it.each<[string, string | null, string]>([
        ['a rolling interval', null, '1440'],
        ['a plain daily cron', '0 9 * * *', SCOUT_DAILY_AT_SCHEDULE_MODE],
        ['a single weekday cron', '30 8 * * 4', SCOUT_WEEKLY_ON_SCHEDULE_MODE],
        ['a Sunday cron written as 7', '30 8 * * 7', SCOUT_WEEKLY_ON_SCHEDULE_MODE],
        ['a weekday-range cron', '0 9 * * 1-5', SCOUT_CUSTOM_CRON_SCHEDULE_MODE],
        ['a monthly cron', '0 9 1 * *', SCOUT_CUSTOM_CRON_SCHEDULE_MODE],
    ])('reads %s as its own mode', (_label, runCronSchedule, expected) => {
        expect(getScoutScheduleMode({ run_interval_minutes: 1440, run_cron_schedule: runCronSchedule })).toEqual(
            expected
        )
    })

    it('round-trips a weekly day and time through the cron it writes', () => {
        expect(dayTimeToWeeklyCron('4', '08:30')).toEqual('30 8 * * 4')
        expect(weeklyCronToDayTime('30 8 * * 4')).toEqual({ day: '4', time: '08:30' })
    })

    it('reads the other Sunday spelling as the dropdown value', () => {
        expect(weeklyCronToDayTime('30 8 * * 7')).toEqual({ day: '0', time: '08:30' })
    })

    describe('scoutCronScheduleError', () => {
        it.each<[string, string]>([
            ['0 9 * * 1-5', 'weekdays'],
            ['30 8 * * 1,4', 'two days a week'],
            ['0 9 1 * *', 'the first of the month'],
            ['0 9,17 * * *', 'twice a day'],
            ['0 9 * * MON', 'a named weekday'],
            ['0 9 15 2 *', 'a real February date'],
            ['0 9 * * 5#2', 'syntax only the backend models'],
        ])('accepts %s (%s)', (expression) => {
            expect(scoutCronScheduleError(expression)).toBeNull()
        })

        it.each<[string, string]>([
            ['0 9 * *', 'Enter a five-field cron expression, like 0 9 * * 1-5.'],
            ['70 9 * * *', 'Enter a five-field cron expression, like 0 9 * * 1-5.'],
            ['not a cron at all', 'Enter a five-field cron expression, like 0 9 * * 1-5.'],
            ['0 0 31 2 *', 'This schedule never matches a real date. Check the day and month.'],
            ['*/20 * * * *', 'Runs must be at least 30 minutes apart.'],
            ['0,15 9 * * *', 'Runs must be at least 30 minutes apart.'],
        ])('refuses %s', (expression, expected) => {
            expect(scoutCronScheduleError(expression)).toEqual(expected)
        })
    })
})
