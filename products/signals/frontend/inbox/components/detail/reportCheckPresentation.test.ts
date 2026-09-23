import { dayjs } from 'lib/dayjs'

import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReportArtefact } from '../../types'
import {
    buildReportCheckRows,
    checkCancelledEntry,
    checkExpiredEntry,
    checkScheduledEntry,
    latestCheckExplanations,
    reportChecksMeta,
    splitReportCheckRows,
} from './reportCheckPresentation'

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
    const [row] = buildReportCheckRows([makeCheck(overrides)], explanations)
    return { tag: row.tag.label, detail: row.detail }
}

describe('reportCheckPresentation', () => {
    describe('buildReportCheckRows', () => {
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
                new Map()
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
            const [row] = buildReportCheckRows([makeCheck({ status })], new Map())
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
                new Map()
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
            ['says nothing is left to run', [{ status: 'passed' }, { status: 'failed' }], '2 · all done'],
        ])('%s', (_name, overrides, expected) => {
            expect(reportChecksMeta(overrides.map((o) => makeCheck(o)))).toEqual(expected)
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
        it('gives a dated check its run date and the scout that answers it', () => {
            expect(
                checkScheduledEntry({
                    kind: 'agent',
                    next_run_at: '2026-09-27T09:00:00Z',
                    arms_on_resolve: false,
                    skill_name: 'signals-scout-error-tracking',
                    runs: 2,
                })
            ).toEqual({
                tag: { label: 'Runs Sep 27', type: 'primary' },
                detail: 'Error tracking scout runs it · 2 runs',
            })
        })

        it('says a check on an unresolved report waits for the resolve rather than naming a date it cannot keep', () => {
            expect(
                checkScheduledEntry({
                    kind: 'metric_threshold',
                    next_run_at: '2026-09-27T09:00:00Z',
                    arms_on_resolve: true,
                    soak_minutes: 4320,
                })
            ).toEqual({
                tag: { label: 'Waiting for resolve', type: 'muted' },
                detail: 'Starts 3 days after this report is resolved',
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
            expect(checkCancelledEntry({}).detail).toEqual('Stopped before it could settle')
        })
    })
})
