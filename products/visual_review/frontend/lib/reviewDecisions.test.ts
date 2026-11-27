import type { RunApi, RunProgressApi } from '../generated/api.schemas'
import { decisionErrorOutcome, finalizeButtonCopy, olderRunSituation } from './reviewDecisions'

const progress = (overrides: Partial<RunProgressApi>): RunProgressApi => ({
    total: 20,
    approved: 0,
    approved_on_earlier_commits: 0,
    approved_via_mcp: 0,
    rejected: 0,
    needs_review: 0,
    tolerated: 0,
    ...overrides,
})

const noRejections = { count: 0, rejecter: null, byAgent: false, commitSha: null }

const ledgerRun = (overrides: Partial<RunApi>): RunApi =>
    ({
        id: 'older',
        commit_sha: 'abc1234def',
        pr_number: 42,
        purpose: 'review',
        gate: 'commit_status',
        approved: false,
        ...overrides,
    }) as RunApi

describe('reviewDecisions', () => {
    test.each([
        {
            name: 'nothing decided',
            input: progress({ needs_review: 20 }),
            rejections: noRejections,
            expected: {
                label: 'Accept 20 and finalize',
                note: '20 to review',
                tooltip: 'Accepts every change, removals included, and passes the gate.',
                disabledReason: null,
            },
        },
        {
            name: 'some accepted on earlier commits',
            input: progress({ approved: 18, approved_on_earlier_commits: 12, needs_review: 2 }),
            rejections: noRejections,
            expected: {
                label: 'Accept 2 and finalize',
                note: '18 accepted (12 on earlier commits), 2 to review',
                tooltip: 'Accepts the 2 changes left and passes the gate.',
                disabledReason: null,
            },
        },
        {
            name: 'a rejection blocks finalize',
            input: progress({ approved: 18, approved_on_earlier_commits: 12, rejected: 1, needs_review: 1 }),
            rejections: { count: 1, rejecter: 'bob', byAgent: false, commitSha: '5e6f7a8' },
            expected: {
                label: 'Accept 1 and finalize',
                note: '18 accepted, 1 rejected, 1 to review',
                tooltip: null,
                disabledReason:
                    'bob rejected 1 change. Finalize works once it has a new picture or bob undoes the rejection.',
            },
        },
        {
            name: "an agent's rejection names the agent",
            input: progress({ approved: 18, rejected: 2 }),
            rejections: { count: 2, rejecter: 'alice', byAgent: true, commitSha: null },
            expected: {
                label: 'Finalize run',
                note: '18 accepted, 2 rejected',
                tooltip: null,
                disabledReason:
                    'An agent for alice rejected 2 changes. Finalize works once they have new pictures or alice undoes the rejections.',
            },
        },
        {
            name: 'all accepted',
            input: progress({ approved: 20, approved_on_earlier_commits: 12 }),
            rejections: noRejections,
            expected: {
                label: 'Finalize run',
                note: '20 accepted (12 on earlier commits)',
                tooltip: 'Passes the gate with 20 accepted changes.',
                disabledReason: null,
            },
        },
        {
            name: 'all accepted, some by an agent',
            input: progress({ approved: 20, approved_via_mcp: 6 }),
            rejections: noRejections,
            expected: {
                label: 'Finalize run',
                note: '20 accepted, 6 by an agent',
                tooltip: '6 changes were accepted by an agent. Finalizing passes the gate with them.',
                disabledReason: null,
            },
        },
        {
            name: 'only quarantined changes accepted',
            input: progress({ total: 0 }),
            rejections: noRejections,
            expected: {
                label: 'Finalize run',
                note: null,
                tooltip: 'Records the accepted pictures of quarantined stories.',
                disabledReason: null,
            },
        },
    ])('finalize button: $name', ({ input, rejections, expected }) => {
        expect(finalizeButtonCopy(input, rejections)).toEqual(expected)
    })

    const head = { id: 'head', commit_sha: 'def5678abc', status: 'completed', approved: false }
    test.each([
        { name: 'yaml-mode run', run: ledgerRun({ gate: 'ci_job', head_run: head }), expected: null },
        { name: 'the newest run itself', run: ledgerRun({ id: 'head', head_run: head }), expected: null },
        {
            name: 'newest run processing',
            run: ledgerRun({ head_run: { ...head, status: 'processing' } }),
            expected: 'head_processing',
        },
        { name: 'newest run ready', run: ledgerRun({ head_run: head }), expected: 'head_ready' },
        {
            name: 'newest run finalized',
            run: ledgerRun({ head_run: { ...head, approved: true } }),
            expected: 'head_finalized',
        },
    ])('older run situation: $name', ({ run, expected }) => {
        expect(olderRunSituation(run)).toBe(expected)
    })

    test.each([
        {
            name: 'a decision made since reloads the page',
            error: {
                status: 409,
                code: 'decided_since',
                detail: 'raw',
                data: { snapshots: [{ code: 'decided_since' }] },
            },
            expected: {
                code: 'decided_since',
                message: 'Someone decided on this change after you opened it. The page now shows the newest decision.',
                refresh: true,
            },
        },
        {
            name: 'an unknown refusal shows the server text',
            error: { status: 400, code: 'hash_mismatch', detail: 'The run renders another picture.', data: {} },
            expected: { code: 'hash_mismatch', message: 'The run renders another picture.', refresh: false },
        },
        {
            name: 'a network failure falls back',
            error: new Error('offline'),
            expected: { code: null, message: 'Could not accept the change.', refresh: false },
        },
    ])('decision error: $name', ({ error, expected }) => {
        expect(decisionErrorOutcome(error, 'Could not accept the change.')).toEqual(expected)
    })
})
