import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { dayjs } from 'lib/dayjs'

import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReportArtefact } from '../../types'
import {
    buildReportCheckRows,
    checkCancelledEntry,
    checkExpiredEntry,
    checkScheduledEntry,
    latestCheckExplanations,
    monitoringPeriodLabel,
    reportChecksMeta,
    splitReportCheckRows,
} from './reportCheckPresentation'
import { ReportCheckTiming } from './ReportCheckTiming'

function makeCheck(overrides: Partial<SignalReportCheckApi> = {}): SignalReportCheckApi {
    return {
        id: 'check-1',
        title: 'Checkout errors stay at zero',
        rationale: 'The retry fix should stop the exception.',
        kind: 'agent',
        status: 'active',
        config: { instructions: 'Re-read the issue.', skill_name: 'signals-scout-error-tracking', probe_hints: [] },
        next_run_at: '2026-09-27T09:00:00Z',
        soak_minutes: 10080,
        run_interval_minutes: null,
        runs_remaining: 1,
        expires_at: '2026-10-27T09:00:00Z',
        last_run_at: null,
        last_outcome: null,
        last_outcome_reason: null,
        dispatched_at: null,
        consecutive_errors: 0,
        created_at: '2026-09-20T09:00:00Z',
        updated_at: '2026-09-20T09:00:00Z',
        ...overrides,
    } as SignalReportCheckApi
}

function rowFor(
    overrides: Partial<SignalReportCheckApi>,
    explanations = new Map<string, string>()
): {
    tag: string
    detail: string
} {
    const [row] = buildReportCheckRows([makeCheck(overrides)], explanations, 'monitoring')
    return { tag: row.tag.label, detail: row.detail }
}

describe('reportCheckPresentation', () => {
    it.each([
        [0, '0 minutes'],
        [1, '1 minute'],
        [1441, '1 day 1 minute'],
        [1501, '1 day 1 hour 1 minute'],
        [20160, '14 days'],
    ])('preserves the full Monitoring period of %s minutes', (minutes, label) => {
        expect(monitoringPeriodLabel(Number(minutes))).toBe(label)
    })

    describe('buildReportCheckRows', () => {
        it('hides cached measurement dates after the report leaves Monitoring', () => {
            const markup = renderToStaticMarkup(
                createElement(ReportCheckTiming, {
                    check: makeCheck({
                        monitoring_timing: {
                            state: 'scheduled',
                            started_at: '2026-09-20T09:00:00Z',
                            ends_at: '2026-09-27T09:00:00Z',
                            next_measurement_at: '2026-09-21T09:00:00Z',
                        },
                    }),
                    reportStatus: 'resolved',
                    detail: 'Checks run only while this report is in Monitoring.',
                })
            )
            expect(markup).toContain('Checks run only while this report is in Monitoring.')
            expect(markup).not.toContain('Next measurement:')
            expect(markup).not.toContain('Window end:')
        })

        it.each(['resolved', 'closed', 'ready', 'suppressed', 'potential'] as const)(
            'pauses open checks on a %s report without hiding historical verdicts',
            (reportStatus) => {
                const checks = [
                    makeCheck({ id: 'pending', status: 'pending' }),
                    makeCheck({ id: 'scheduled', kind: 'metric_threshold' }),
                    makeCheck({ id: 'dispatched', dispatched_at: '2026-09-21T09:00:00Z' }),
                    makeCheck({
                        id: 'stale-timing',
                        monitoring_timing: {
                            state: 'scheduled',
                            started_at: null,
                            ends_at: null,
                            next_measurement_at: '2026-09-27T09:00:00Z',
                        },
                    }),
                    makeCheck({ id: 'passed', status: 'passed', last_run_at: '2026-09-27T09:00:00Z' }),
                ]
                const rows = buildReportCheckRows(checks, new Map([['passed', 'The expectation held.']]), reportStatus)
                for (const row of rows.filter(({ cancellable }) => cancellable)) {
                    expect(row.tag).toEqual({ label: 'Paused', type: 'muted' })
                    expect(row.detail).toBe('Checks run only while this report is in Monitoring.')
                    expect(row.check).toBe(checks.find(({ id }) => id === row.check.id))
                }
                expect(rows.find(({ check }) => check.id === 'passed')?.detail).toBe('Sep 27 · The expectation held.')
                expect(reportChecksMeta(checks, reportStatus)).toBe('5 · paused')
            }
        )

        // The section exists so a reader can tell a scheduled check from a waiting one from a check
        // that never ran. A wrong mapping here puts the wrong verdict word on the row.
        it.each<[string, Partial<SignalReportCheckApi>, string, string]>([
            [
                'a check waiting for the report to resolve names its soak',
                { status: 'pending' },
                'Waiting',
                'Starts 7 days after this report is resolved · Error tracking runs it',
            ],
            [
                'a pending metric check names its minimum wait',
                { status: 'pending', kind: 'metric_threshold', soak_minutes: 1440 },
                'Waiting',
                'At least 1 day after this report is resolved',
            ],
            [
                'a Monitoring deadline does not promise another run',
                {
                    monitoring_timing: {
                        state: 'window_ended',
                        started_at: '2026-09-20T09:00:00Z',
                        ends_at: '2026-09-27T09:00:00Z',
                        next_measurement_at: null,
                    },
                },
                'Awaiting verification',
                'The observation window has ended. Interim measurements have stopped. A final verdict has not been recorded.',
            ],
            [
                'a paused Monitoring check does not promise a scout run',
                {
                    monitoring_timing: {
                        state: 'paused',
                        started_at: '2026-09-20T09:00:00Z',
                        ends_at: '2026-09-27T09:00:00Z',
                        next_measurement_at: null,
                    },
                },
                'Paused',
                'This check is paused during Monitoring.',
            ],
            [
                'a scheduled check leads with its run date and its lane',
                {},
                'Runs Sep 27',
                'Error tracking re-probes the claim · 1 run · 7 days soak',
            ],
            [
                'a scheduled metric check says the coordinator measures it',
                {
                    kind: 'metric_threshold',
                    config: { comparison: { operator: 'lte', value: 20 } },
                    soak_minutes: null,
                },
                'Runs Sep 27',
                'Measures the metric again · 1 run',
            ],
            [
                'a passed check reports the verdict, not the status name',
                { status: 'passed', last_run_at: '2026-09-27T09:00:00Z' },
                'Still holds',
                'Sep 27 · 11 rageclicks in the last 14 days.',
            ],
            [
                'a failed check reads as the claim no longer holding',
                { status: 'failed', last_run_at: '2026-09-27T09:00:00Z' },
                'No longer holds',
                'Sep 27 · 11 rageclicks in the last 14 days.',
            ],
            [
                'an errored check says how many tries it took before giving up',
                { status: 'errored', last_run_at: '2026-09-27T09:00:00Z', consecutive_errors: 3 },
                "Couldn't measure",
                'Gave up after 3 tries · Sep 27 · 11 rageclicks in the last 14 days.',
            ],
            [
                'an inconclusive check reads apart from errored and says why in plain words',
                {
                    status: 'inconclusive',
                    last_run_at: '2026-09-27T09:00:00Z',
                    last_outcome: 'inconclusive',
                    last_outcome_reason: 'needs_manual_verification',
                },
                'Inconclusive',
                'Needs a person to verify · Sep 27 · 11 rageclicks in the last 14 days.',
            ],
            [
                'an open check waiting on data says why it looks again',
                { last_outcome: 'inconclusive', last_outcome_reason: 'awaiting_data', soak_minutes: null },
                'Runs Sep 27',
                'Not enough data yet, looks again · 1 run',
            ],
            [
                'a check that expired before its first run says so',
                { status: 'expired', updated_at: '2026-10-27T09:00:00Z' },
                'Never ran',
                'Expired Oct 27 before it ever ran',
            ],
            [
                'a check that ran and then expired keeps its last run visible',
                { status: 'expired', last_run_at: '2026-09-27T09:00:00Z', updated_at: '2026-10-27T09:00:00Z' },
                'Expired',
                'Last ran Sep 27 · expired Oct 27',
            ],
            [
                'a cancelled check says when it was stopped',
                { status: 'cancelled', updated_at: '2026-09-21T09:00:00Z' },
                'Cancelled',
                'Stopped Sep 21',
            ],
        ])('%s', (_name, overrides, tag, detail) => {
            expect(rowFor(overrides, new Map([['check-1', '11 rageclicks in the last 14 days.']]))).toEqual({
                tag,
                detail,
            })
        })

        it('reads a dispatched agent check as running rather than as scheduled', () => {
            // Dispatch pushes `next_run_at` out to the result window, so `dispatched_at` is the only
            // field that separates a run in flight from one still waiting for its date.
            const { tag, detail } = rowFor({
                dispatched_at: dayjs().subtract(20, 'minutes').toISOString(),
                next_run_at: dayjs().add(2, 'hours').toISOString(),
            })
            expect(tag).toEqual('Running')
            expect(detail).toEqual('Error tracking started 20 minutes ago')
        })

        it('leads with what is happening now and trails with the checks that never decided', () => {
            // A check retired later than a verdict landed must not outrank it: the retired rows are
            // also the ones that fold away, so they belong at the end of the band.
            const rows = buildReportCheckRows(
                [
                    makeCheck({ id: 'expired', status: 'expired', updated_at: '2026-10-27T09:00:00Z' }),
                    makeCheck({ id: 'passed', status: 'passed', last_run_at: '2026-09-20T09:00:00Z' }),
                    makeCheck({ id: 'pending', status: 'pending' }),
                    makeCheck({ id: 'later', next_run_at: '2026-10-04T09:00:00Z' }),
                    makeCheck({ id: 'running', dispatched_at: '2026-09-21T09:00:00Z' }),
                    makeCheck({ id: 'sooner', next_run_at: '2026-09-27T09:00:00Z' }),
                ],
                new Map(),
                'monitoring'
            )
            expect(rows.map((row) => row.check.id)).toEqual([
                'running',
                'sooner',
                'later',
                'pending',
                'passed',
                'expired',
            ])
        })

        it.each<[string, SignalReportCheckApi['status'], boolean]>([
            ['a scheduled check', 'active', true],
            ['a check waiting for the resolve', 'pending', true],
            ['a check that already decided', 'passed', false],
        ])('offers Stop on %s', (_name, status, cancellable) => {
            const [row] = buildReportCheckRows([makeCheck({ status })], new Map(), 'monitoring')
            expect(row.cancellable).toEqual(cancellable)
        })
    })

    describe('splitReportCheckRows', () => {
        it('folds only the retired rows past the fourth, never a check still running', () => {
            const rows = buildReportCheckRows(
                [
                    ...[1, 2, 3, 4].map((n) =>
                        makeCheck({ id: `cancelled-${n}`, status: 'cancelled', updated_at: `2026-09-0${n}T09:00:00Z` })
                    ),
                    makeCheck({ id: 'running', dispatched_at: '2026-09-21T09:00:00Z' }),
                    makeCheck({ id: 'scheduled' }),
                ],
                new Map(),
                'monitoring'
            )
            const { visible, hidden } = splitReportCheckRows(rows)
            expect(visible.map((row) => row.check.id)).toEqual(['running', 'scheduled', 'cancelled-4', 'cancelled-3'])
            expect(hidden.map((row) => row.check.id)).toEqual(['cancelled-2', 'cancelled-1'])
        })
    })

    describe('reportChecksMeta', () => {
        it.each<[string, Partial<SignalReportCheckApi>[], string]>([
            [
                'names the soonest run while anything is scheduled',
                [
                    { next_run_at: '2026-10-04T09:00:00Z' },
                    { next_run_at: '2026-09-27T09:00:00Z' },
                    { status: 'passed' },
                ],
                '3 · next Sep 27',
            ],
            [
                'says a run is under way rather than quoting its answer-by deadline',
                [{ dispatched_at: '2026-09-21T09:00:00Z' }, { next_run_at: '2026-09-27T09:00:00Z' }],
                '2 · running now',
            ],
            ['says what pending checks are waiting on', [{ status: 'pending' }], '1 · waiting for resolve'],
            [
                'does not advertise a closed Monitoring window as the next run',
                [
                    {
                        monitoring_timing: {
                            state: 'window_ended',
                            started_at: null,
                            ends_at: null,
                            next_measurement_at: null,
                        },
                    },
                ],
                '1',
            ],
            ['says nothing is left to run', [{ status: 'passed' }, { status: 'failed' }], '2 · all done'],
        ])('%s', (_name, overrides, expected) => {
            expect(
                reportChecksMeta(
                    overrides.map((o) => makeCheck(o)),
                    'monitoring'
                )
            ).toEqual(expected)
        })
    })

    describe('latestCheckExplanations', () => {
        it('keeps the newest verdict per check and ignores every other artefact', () => {
            const artefacts = [
                { type: 'check_result', content: { check_id: 'a', explanation: 'newest' } },
                { type: 'check_result', content: { check_id: 'a', explanation: 'older' } },
                { type: 'check_result', content: { check_id: 'b', explanation: '  ' } },
                { type: 'commit', content: { check_id: 'a', explanation: 'not a verdict' } },
            ] as unknown as SignalReportArtefact[]
            expect(latestCheckExplanations(artefacts)).toEqual(new Map([['a', 'newest']]))
        })
    })

    describe('lifecycle log entries', () => {
        it.each([false, true])('gives a dated check its run date with monitoring enabled: %s', (monitoringEnabled) => {
            expect(
                checkScheduledEntry(
                    {
                        kind: 'agent',
                        next_run_at: '2026-09-27T09:00:00Z',
                        arms_on_resolve: false,
                        skill_name: 'signals-scout-error-tracking',
                        runs: 2,
                    },
                    monitoringEnabled
                )
            ).toEqual({
                tag: { label: 'Runs Sep 27', type: 'primary' },
                detail: 'Error tracking scout runs it · 2 runs',
            })
        })

        it.each([
            [4320, '3 days'],
            [10076, '7 days'],
            [2160, '1 day 12 hours'],
            [95, '2 hours'],
            [45, '45 minutes'],
        ])(
            'says a check on an unresolved report waits for the resolve, with a %i minute soak as %s',
            (soakMinutes, label) => {
                expect(
                    checkScheduledEntry({
                        kind: 'metric_threshold',
                        next_run_at: '2026-09-27T09:00:00Z',
                        arms_on_resolve: true,
                        soak_minutes: soakMinutes,
                    })
                ).toEqual({
                    tag: { label: 'Waiting for resolve', type: 'muted' },
                    detail: `At least ${label} after this report is resolved · Waits for a full query window`,
                })
            }
        )

        it.each([
            ['metric_threshold', 480, 'Final evaluation after 8 hours of monitoring'],
            ['metric_threshold', 720, 'Final evaluation after 12 hours of monitoring'],
            ['metric_threshold', 95, 'Final evaluation after 1 hour 35 minutes of monitoring'],
            ['metric_threshold', 0, 'Final evaluation when monitoring starts'],
            ['metric_threshold', null, 'Final evaluation during monitoring'],
            ['agent', 480, 'Final evaluation after 8 hours of monitoring · The follow-up scout runs it'],
            ['agent', 0, 'Final evaluation when monitoring starts · The follow-up scout runs it'],
        ])('describes final evaluation for a pending %s check (soak_minutes=%s)', (kind, soakMinutes, detail) => {
            expect(checkScheduledEntry({ kind, arms_on_resolve: true, soak_minutes: soakMinutes }, true)).toEqual({
                tag: { label: 'Runs during monitoring', type: 'muted' },
                detail,
            })
        })

        it('separates a check that never ran from one that ran and never settled', () => {
            expect(checkExpiredEntry({}).tag.label).toEqual('Never ran')
            expect(checkExpiredEntry({ last_run_at: '2026-09-20T09:00:00Z' })).toEqual({
                tag: { label: 'Expired', type: 'muted' },
                detail: 'Last ran Sep 20 · retired at its horizon before it settled',
            })
        })

        it('names which path stopped a check, and falls back when the reason is unknown', () => {
            expect(checkCancelledEntry({ reason: 'replaced_by_research' }).detail).toEqual(
                'Replaced when research re-ran on this report and wrote a new check'
            )
            expect(checkCancelledEntry({ reason: 'replaced_by_request' }).detail).toEqual(
                'Replaced on request by a revised check'
            )
            expect(checkCancelledEntry({}).detail).toEqual('Stopped before it could settle')
        })
    })
})
