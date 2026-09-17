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
})
