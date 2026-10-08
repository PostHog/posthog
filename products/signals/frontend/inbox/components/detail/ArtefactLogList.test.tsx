import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { mockTask } from '../../__mocks__/inboxMocks'
import { SignalReportArtefact } from '../../types'
import { ArtefactLogList } from './ArtefactLogList'

function makeArtefact(content: Record<string, any>, type = 'implementation_decision'): SignalReportArtefact {
    return {
        id: 'artefact-1',
        type,
        content,
        created_at: '2026-06-11T10:00:00Z',
    }
}

describe('ArtefactLogList', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['a replacement recommendation', true, undefined, 'Replacement recommended'],
        ['a kept PR', false, undefined, 'Still the right fix'],
        ['a capped request', false, 'revision_limit', 'Replacement limit reached'],
    ])('shows the decision and its reason for %s', (_name, supersede, blocked_reason, expectedTag) => {
        render(
            <ArtefactLogList
                reportId="report-1"
                artefacts={[
                    makeArtefact({ supersede, blocked_reason, reason: 'The root cause moved to the ingestion path.' }),
                ]}
            />
        )

        expect(screen.getByText('Open PR assessed')).toBeInTheDocument()
        expect(screen.queryByText('implementation_decision')).not.toBeInTheDocument()
        expect(screen.getByText(expectedTag)).toBeInTheDocument()
        expect(screen.getByText('The root cause moved to the ingestion path.')).toBeInTheDocument()
    })

    it('labels an inconclusive check result and explains why', () => {
        render(
            <ArtefactLogList
                reportId="report-1"
                artefacts={[
                    makeArtefact(
                        { outcome: 'inconclusive', explanation: 'The measurement window cannot fit before expiry.' },
                        'check_result'
                    ),
                ]}
            />
        )
        expect(screen.getByText('Inconclusive')).toBeInTheDocument()
        expect(screen.getByText('The measurement window cannot fit before expiry.')).toBeInTheDocument()
    })

    it('links the selected predecessors when a replacement starts', () => {
        const oldPr = 'https://github.com/example/repo/pull/1'
        render(
            <ArtefactLogList
                reportId="report-1"
                artefacts={[makeArtefact({ decision: { targets: [{ pr_url: oldPr }] } }, 'implementation_replacement')]}
            />
        )
        expect(screen.getByText('Replacing PR #1')).toBeInTheDocument()
        expect(screen.getByText('Pull request #1').closest('a')).toHaveAttribute('href', oldPr)
        expect(screen.queryByText('Replaced')).not.toBeInTheDocument()
    })

    it('shows the replacement and individual outcomes without exposing internal retry records', () => {
        const oldPr = 'https://github.com/example/repo/pull/1'
        const keptPr = 'https://github.com/example/repo/pull/2'
        const newPr = 'https://github.com/example/repo/pull/3'
        render(
            <ArtefactLogList
                reportId="report-1"
                artefacts={[
                    {
                        ...makeArtefact(
                            { status: 'processing', explanation: 'Internal lease' },
                            'implementation_handover'
                        ),
                        id: 'retry',
                    },
                    makeArtefact(
                        {
                            status: 'needs_attention',
                            explanation: 'Review the remaining PRs.',
                            replacement_pr_urls: [newPr],
                            results: { [oldPr]: 'closed', [keptPr]: 'skipped' },
                        },
                        'implementation_handover'
                    ),
                ]}
            />
        )
        for (const [index, url] of [oldPr, keptPr, newPr].entries()) {
            expect(screen.getByText(`Pull request #${index + 1}`).closest('a')).toHaveAttribute('href', url)
            expect(screen.queryByText(url)).not.toBeInTheDocument()
        }
        expect(screen.getByText('PR replacement needs attention')).toBeInTheDocument()
        expect(screen.getByText(/Not closed by PostHog/)).toBeInTheDocument()
        expect(screen.queryByText('Internal lease')).not.toBeInTheDocument()
    })

    it.each([
        ['closed', 'PR #3 replaced #1'],
        ['skipped', 'PR replacement completed'],
    ])('describes a completed replacement with a %s predecessor', (result, heading) => {
        render(
            <ArtefactLogList
                reportId="report-1"
                artefacts={[
                    makeArtefact(
                        {
                            status: 'completed',
                            replacement_pr_urls: ['https://github.com/example/repo/pull/3'],
                            results: { 'https://github.com/example/repo/pull/1': result },
                        },
                        'implementation_handover'
                    ),
                ]}
            />
        )
        expect(screen.getByText(heading)).toBeInTheDocument()
    })

    it.each([true, false])('uses only the task attached to this PR for its title (available: %s)', (hasTask) => {
        const url = 'https://github.com/example/repo/pull/3'
        render(
            <ArtefactLogList
                reportId="report-1"
                artefacts={[makeArtefact({ url }, 'pull_request')]}
                knownTasks={
                    new Map([
                        ['unrelated', { ...mockTask('unrelated'), title: 'Unrelated implementation' }],
                        ...(hasTask
                            ? [
                                  [
                                      'task-3',
                                      {
                                          ...mockTask('task-3'),
                                          title: 'Implementation: Handle blocked browser storage',
                                      },
                                  ] as const,
                              ]
                            : []),
                    ])
                }
                pullRequests={[
                    {
                        id: 'pr-3',
                        url,
                        state: 'unknown',
                        merged: false,
                        review_decision: null,
                        merged_at: null,
                        claim_id: null,
                        attached_at: null,
                        attached_by: { kind: 'task', user: null, agent: null, task_id: 'task-3' },
                    },
                ]}
            />
        )
        expect(screen.getByText('PR #3 linked')).toBeInTheDocument()
        expect(
            screen.getByText(hasTask ? 'Handle blocked browser storage' : 'Pull request #3').closest('a')
        ).toHaveAttribute('href', url)
        expect(screen.getByText('Status unavailable')).toBeInTheDocument()
        expect(screen.queryByText('Unrelated implementation')).not.toBeInTheDocument()
        expect(screen.queryByText('Open')).not.toBeInTheDocument()
    })

    // Without a branch for this type the row falls through to the raw type name and the reader
    // cannot tell why nothing started, which is the whole point of the entry.
    it.each([
        ['duplicate_of', 'Duplicate'],
        ['blocked_by_dependency', 'Waiting on a dependency'],
        ['plan_parent', 'Tracked by other reports'],
    ])('says why automatic work was held back for %s', (skipReason, expectedTag) => {
        render(
            <ArtefactLogList
                reportId="report-1"
                artefacts={[
                    makeArtefact(
                        {
                            skip_reason: skipReason,
                            linked_report_id: '0198c0de-0000-7000-8000-000000000001',
                            detail: 'No work started here because a report this one depends on has no pull request yet.',
                        },
                        'autostart_skip'
                    ),
                ]}
            />
        )

        expect(screen.getByText('Work not started')).toBeInTheDocument()
        expect(screen.queryByText('autostart_skip')).not.toBeInTheDocument()
        expect(screen.getByText(expectedTag)).toBeInTheDocument()
        expect(screen.getByText('Open that report').closest('a')).toHaveAttribute(
            'href',
            expect.stringContaining('0198c0de-0000-7000-8000-000000000001')
        )
    })

    it('shows the served ranking model heads, highest lift first, with challengers behind a disclosure', () => {
        const { container } = render(
            <ArtefactLogList
                reportId="report-1"
                artefacts={[
                    makeArtefact(
                        {
                            scored_at: '2026-06-11T09:00:00Z',
                            manifest_version: '12',
                            served_key: 'report_embeddings@2026-06-10',
                            results: {
                                'report_embeddings@2026-06-10': {
                                    status: 'scored',
                                    roles: ['served'],
                                    scores: { pr_merged: 0.52, action: 0.78, refund: 0.04, open: 0.9 },
                                    lifts: { action: 1.5 },
                                    metadata: {
                                        heads: [
                                            { head: 'action', readable: true, refit_classification_threshold: 0.6 },
                                            { head: 'pr_merged', readable: true, refit_classification_threshold: 0.2 },
                                            { head: 'refund', readable: false, refit_classification_threshold: 0.01 },
                                            { head: 'open', readable: true },
                                        ],
                                    },
                                },
                                'signal_counts@2026-06-10': {
                                    status: 'skipped',
                                    roles: ['challenger'],
                                    skip_reason: 'missing report vector',
                                    scores: {},
                                },
                            },
                        },
                        'ranking_score'
                    ),
                ]}
            />
        )

        expect(screen.getByText('Ranking scored')).toBeInTheDocument()
        // Stored lifts win over the metadata threshold, and a head with no threshold sorts last.
        expect(screen.getAllByText(/^[\d.]+x$/).map((node) => node.textContent)).toEqual(['4.0x', '2.6x', '1.5x'])
        expect(screen.getAllByText(/^[\d.]+%$/).map((node) => node.textContent)).toEqual(['4.0%', '52%', '78%', '90%'])
        expect(screen.getByLabelText('No holdout read for this head yet').closest('span')).toHaveTextContent('4.0%')
        expect(screen.getByText('Other models (1)')).toBeInTheDocument()
        expect(container.querySelector('details')).not.toHaveAttribute('open')
        expect(screen.getByText('Skipped: missing report vector')).toBeInTheDocument()
    })

    it.each([
        ['a served key missing from the results', { served_key: 'gone@1', results: {} }],
        ['content with no results', { served_key: 'a@1' }],
        ['a served result with an unknown status', { served_key: 'a@1', results: { 'a@1': { status: 'pending' } } }],
    ])('falls back to the ranking label alone for %s', (_name, content) => {
        const { container } = render(
            <ArtefactLogList reportId="report-1" artefacts={[makeArtefact(content, 'ranking_score')]} />
        )
        expect(screen.getByText('Ranking scored')).toBeInTheDocument()
        expect(container.querySelector('.LemonCard')).not.toBeInTheDocument()
    })

    it.each([
        ['work_claim', { display_name: 'Ada' }, 'Work claimed', 'Ada'],
        ['work_release', { reason: 'taken_over' }, 'Work released', 'Taken over'],
    ])('labels a %s row', (type, content, label, detail) => {
        render(<ArtefactLogList reportId="report-1" artefacts={[makeArtefact(content, type)]} />)
        expect(screen.getByText(label)).toBeInTheDocument()
        expect(screen.getByText(detail)).toBeInTheDocument()
    })
})
