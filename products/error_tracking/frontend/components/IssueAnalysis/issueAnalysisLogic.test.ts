import type { SignalNode } from 'scenes/debug/signals/types'
import { SignalReport, SignalReportArtefact, SignalReportStatus } from 'scenes/inbox/types'

import { deriveIssueAnalysisCta, extractIssueFindings, IssueAnalysisCta, pickPrimaryReport } from './issueAnalysisLogic'

const ISSUE_ID = 'issue-1'

function report(overrides: Partial<SignalReport> = {}): SignalReport {
    return {
        id: 'report-1',
        title: 'fix(err): handle null user',
        summary: 'A null user crashes the profile page.',
        status: SignalReportStatus.READY,
        total_weight: 1,
        signal_count: 1,
        relevant_user_count: null,
        created_at: '2026-07-01T00:00:00Z',
        updated_at: '2026-07-01T00:00:00Z',
        artefact_count: 1,
        is_suggested_reviewer: false,
        actionability: 'immediately_actionable',
        ...overrides,
    }
}

function signal(overrides: Partial<SignalNode> = {}): SignalNode {
    return {
        signal_id: 'sig-1',
        content: '',
        source_product: 'error_tracking',
        source_type: 'issue_created',
        source_id: ISSUE_ID,
        weight: 1,
        timestamp: '2026-07-01T00:00:00Z',
        extra: {},
        ...overrides,
    }
}

function findingArtefact(signalId: string, content: Record<string, any> = {}): SignalReportArtefact {
    return {
        id: `artefact-${signalId}-${Math.random()}`,
        type: 'signal_finding',
        content: { signal_id: signalId, relevant_code_paths: ['src/profile.ts'], ...content },
        created_at: '2026-07-01T00:00:00Z',
    }
}

describe('issueAnalysisLogic helpers', () => {
    describe('deriveIssueAnalysisCta', () => {
        it.each<[string, Partial<SignalReport>, IssueAnalysisCta]>([
            // An existing PR must win over Create PR, or the card offers a duplicate kickoff.
            ['ready + actionable + PR', { implementation_pr_url: 'https://github.com/x/y/pull/1' }, 'view_pr'],
            ['ready + actionable, no PR', {}, 'create_pr'],
            ['pending input', { status: SignalReportStatus.PENDING_INPUT, actionability: null }, 'create_pr'],
            ['ready + not actionable', { actionability: 'not_actionable' }, null],
            ['ready + already addressed', { already_addressed: true }, null],
            ['research queued', { status: SignalReportStatus.CANDIDATE, actionability: null }, 'in_progress'],
            ['research running', { status: SignalReportStatus.IN_PROGRESS, actionability: null }, 'in_progress'],
            // A researched report reset to potential keeps its analysis — no misleading spinner.
            ['reset to potential, researched', { status: SignalReportStatus.POTENTIAL, actionability: null }, null],
            [
                'fresh potential, unresearched',
                { status: SignalReportStatus.POTENTIAL, title: null, summary: null, actionability: null },
                'in_progress',
            ],
        ])('%s', (_label, overrides, expected) => {
            expect(deriveIssueAnalysisCta(report(overrides))).toBe(expected)
        })
    })

    describe('pickPrimaryReport', () => {
        it('picks the report with the freshest activity', () => {
            const stale = report({ id: 'stale', updated_at: '2026-06-01T00:00:00Z' })
            const fresh = report({ id: 'fresh', updated_at: '2026-07-02T00:00:00Z' })
            expect(pickPrimaryReport([stale, fresh])?.id).toBe('fresh')
            expect(pickPrimaryReport([])).toBeNull()
            expect(pickPrimaryReport(null)).toBeNull()
        })
    })

    describe('extractIssueFindings', () => {
        it("keeps only this issue's signals and the newest finding per signal", () => {
            const signals = [
                signal({ signal_id: 'sig-1' }),
                // Same report, different issue — its finding must not leak into this issue's card.
                signal({ signal_id: 'sig-other', source_id: 'issue-2' }),
                // Non-error-tracking signal whose source_id collides with the issue id.
                signal({ signal_id: 'sig-replay', source_product: 'session_replay' }),
            ]
            const artefacts = [
                findingArtefact('sig-1', { relevant_code_paths: ['src/new.ts'] }), // newest wins
                findingArtefact('sig-1', { relevant_code_paths: ['src/old.ts'] }),
                findingArtefact('sig-other'),
                findingArtefact('sig-replay'),
            ]

            const findings = extractIssueFindings(ISSUE_ID, signals, artefacts)

            expect(findings).toHaveLength(1)
            expect(findings[0].signalId).toBe('sig-1')
            expect(findings[0].codePaths).toEqual(['src/new.ts'])
        })

        it('drops findings with no code paths or commits and tolerates malformed content', () => {
            const artefacts = [
                findingArtefact('sig-1', { relevant_code_paths: [], relevant_commit_hashes: null }),
                { id: 'a', type: 'signal_finding', content: {}, created_at: '2026-07-01T00:00:00Z' },
                {
                    id: 'b',
                    type: 'signal_finding',
                    content: { signal_id: 'sig-1', relevant_code_paths: 'not-an-array', relevant_commit_hashes: ['x'] },
                    created_at: '2026-07-01T00:00:00Z',
                },
            ]
            expect(extractIssueFindings(ISSUE_ID, [signal()], artefacts)).toEqual([])
        })

        it('maps commit hashes with their reasons', () => {
            const artefacts = [
                findingArtefact('sig-1', {
                    relevant_code_paths: [],
                    relevant_commit_hashes: { abc1234: 'introduced the null path' },
                }),
            ]
            const findings = extractIssueFindings(ISSUE_ID, [signal()], artefacts)
            expect(findings[0].commits).toEqual([{ sha: 'abc1234', reason: 'introduced the null path' }])
        })
    })
})
