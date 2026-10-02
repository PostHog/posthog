import '@testing-library/jest-dom'

import { render, screen, within } from '@testing-library/react'

import { makeReport } from '../../__mocks__/inboxMocks'
import { SignalReportStatus } from '../../types'
import { ReportStatusSection } from './ReportStatusSection'

describe('ReportStatusSection', () => {
    it('shows each pull request with one fact per row', () => {
        const report = makeReport({
            status: SignalReportStatus.READY,
            priority: 'P1',
            actionability: 'immediately_actionable',
            pull_requests: [
                {
                    id: 'pr-1',
                    url: 'https://github.com/example/app/pull/42',
                    state: 'open',
                    merged: false,
                    review_decision: 'approved',
                    merged_at: null,
                    claim_id: null,
                    attached_at: null,
                    attached_by: null,
                },
                {
                    id: 'pr-2',
                    url: 'https://github.com/example/sdk/pull/7',
                    state: 'merged',
                    merged: true,
                    review_decision: 'approved',
                    merged_at: '2026-06-11T12:00:00Z',
                    claim_id: null,
                    attached_at: null,
                    attached_by: null,
                },
            ],
            assignee: {
                claim_id: 'claim-1',
                kind: 'agent',
                user: null,
                task_id: null,
                agent: 'Build agent',
                claimed_at: '2026-06-11T10:00:00Z',
            },
        })

        render(<ReportStatusSection report={report} />)

        expect(screen.getByText('Report status')).toBeInTheDocument()
        expect(screen.getByText('Ready')).toBeInTheDocument()
        expect(screen.queryByText('Work')).not.toBeInTheDocument()
        expect(screen.queryByText('In review')).not.toBeInTheDocument()
        expect(screen.getByText('In progress by')).toBeInTheDocument()
        expect(screen.getByText('Build agent')).toBeInTheDocument()
        expect(screen.getByText('P1')).toBeInTheDocument()
        expect(screen.queryByText('Actionability')).not.toBeInTheDocument()
        expect(screen.getByText('example/app#42')).toBeInTheDocument()
        expect(screen.getByText('example/sdk#7')).toBeInTheDocument()
        expect(screen.getByText('Open')).toBeInTheDocument()
        expect(screen.getAllByText('Merged')).toHaveLength(2)
        expect(screen.getByText('Approved')).toBeInTheDocument()
        expect(screen.getByText(/Jun.*11.*2026/)).toBeInTheDocument()
    })

    it.each(['user', 'task', 'system'] as const)('hides %s claims', (kind) => {
        const { container } = render(
            <ReportStatusSection
                report={makeReport({
                    assignee: {
                        claim_id: 'claim-1',
                        kind,
                        user: null,
                        task_id: null,
                        agent: null,
                        claimed_at: '2026-06-11T10:00:00Z',
                    },
                })}
            />
        )

        expect(container).not.toHaveTextContent('In progress by')
    })

    it('hides pull request rows when the report has no pull request', () => {
        const { container } = render(<ReportStatusSection report={makeReport({ pull_requests: [] })} />)

        expect(container).not.toHaveTextContent('Pull request')
    })

    it('hides the review row when GitHub has no review decision', () => {
        const { container } = render(
            <ReportStatusSection
                report={makeReport({
                    pull_requests: [
                        {
                            id: 'pr-1',
                            url: 'https://github.com/example/app/pull/42',
                            state: 'open',
                            merged: false,
                            review_decision: null,
                            merged_at: null,
                            claim_id: null,
                            attached_at: null,
                            attached_by: null,
                        },
                    ],
                })}
            />
        )

        expect(within(container).getByText('Open')).toBeInTheDocument()
        expect(within(container).queryByText('Review')).not.toBeInTheDocument()
        expect(within(container).queryByText('Review unavailable')).not.toBeInTheDocument()
    })

    it('hides the merged time row when GitHub has no merge time', () => {
        const { container } = render(
            <ReportStatusSection
                report={makeReport({
                    pull_requests: [
                        {
                            id: 'pr-1',
                            url: 'https://github.com/example/app/pull/42',
                            state: 'merged',
                            merged: true,
                            review_decision: null,
                            merged_at: null,
                            claim_id: null,
                            attached_at: null,
                            attached_by: null,
                        },
                    ],
                })}
            />
        )

        expect(within(container).getAllByText('Merged')).toHaveLength(1)
        expect(within(container).queryByText('Time unavailable')).not.toBeInTheDocument()
    })
})
