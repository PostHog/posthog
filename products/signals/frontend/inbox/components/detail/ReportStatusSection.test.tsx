import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { makeReport } from '../../__mocks__/inboxMocks'
import { SignalReport, SignalReportStatus } from '../../types'
import { ReportStatusSection } from './ReportStatusSection'

describe('ReportStatusSection', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    const owner = { id: 1, uuid: 'owner-1', first_name: 'Jane', last_name: 'Doe', email: 'jane@example.com' }

    it.each([
        {
            name: 'an agent without a person',
            responsibleUser: null,
            user: null,
            agent: 'Build agent',
            label: 'Build agent',
        },
        {
            name: 'an agent with a responsible person',
            responsibleUser: owner,
            user: null,
            agent: 'Build agent',
            label: 'Jane Doe (via Build agent)',
        },
        {
            name: 'an agent with a legacy user',
            responsibleUser: null,
            user: owner,
            agent: 'Build agent',
            label: 'Jane Doe (via Build agent)',
        },
        {
            name: 'an unnamed agent with a responsible person',
            responsibleUser: owner,
            user: null,
            agent: '  ',
            label: 'Jane Doe (via External agent)',
        },
    ])('shows pull requests and ownership for $name', ({ responsibleUser, user, agent, label }) => {
        const report = makeReport({
            status: SignalReportStatus.READY,
            priority: 'P1',
            actionability: 'immediately_actionable',
            repo_slug: 'example/app',
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
                user,
                task_id: null,
                agent,
                claimed_at: '2026-06-11T10:00:00Z',
                responsible_user: responsibleUser,
            },
        })

        render(<ReportStatusSection report={report} />)

        expect(screen.getByText('Report status')).toBeInTheDocument()
        expect(screen.getByText('Ready')).toBeInTheDocument()
        expect(screen.queryByText('Work')).not.toBeInTheDocument()
        expect(screen.queryByText('In review')).not.toBeInTheDocument()
        expect(screen.getByText('In progress by')).toBeInTheDocument()
        expect(screen.getByText(label)).toBeInTheDocument()
        expect(screen.getByText('P1')).toBeInTheDocument()
        expect(screen.queryByText('Actionability')).not.toBeInTheDocument()
        expect(screen.getByText('#42')).toBeInTheDocument()
        expect(screen.getByText('example/sdk#7')).toBeInTheDocument()
        expect(screen.getByText('Open · Approved')).toBeInTheDocument()
        expect(screen.getByText('Merged')).toBeInTheDocument()
        expect(screen.getByText(/11 Jun/)).toBeInTheDocument()
    })

    const pullRequest = (number: number): NonNullable<SignalReport['pull_requests']>[number] => ({
        id: `pr-${number}`,
        url: `https://github.com/example/app/pull/${number}`,
        state: 'open',
        merged: false,
        review_decision: null,
        merged_at: null,
        claim_id: null,
        attached_at: null,
        attached_by: null,
    })

    it.each([
        { flag: false, pullRequests: [], labels: ['Report status', 'Priority'] },
        { flag: true, pullRequests: [], labels: ['Report status', 'Priority', 'Repository'] },
        { flag: true, pullRequests: [pullRequest(42)], labels: ['Report status', 'Priority', 'Pull requests'] },
    ])(
        'orders the rows when editable decisions is $flag with $pullRequests.length pull requests',
        ({ flag, pullRequests, labels }) => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REPORT_EDITABLE_DECISIONS], {
                [FEATURE_FLAGS.INBOX_REPORT_EDITABLE_DECISIONS]: flag,
            })
            const { container } = render(
                <ReportStatusSection
                    report={makeReport({ priority: 'P2', repo_slug: 'example/app', pull_requests: pullRequests })}
                    onPriorityChange={() => {}}
                />
            )

            expect(Array.from(container.querySelectorAll('dt'), (dt) => dt.textContent)).toEqual(labels)
            expect(screen.getByLabelText('Change report priority')).toBeInTheDocument()
        }
    )

    it('shows the repository in collapsed agent decisions and expands to its row', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REPORT_EDITABLE_DECISIONS], {
            [FEATURE_FLAGS.INBOX_REPORT_EDITABLE_DECISIONS]: true,
        })
        const { container } = render(
            <ReportStatusSection
                report={makeReport({ priority: 'P2', repo_slug: 'example/app', pull_requests: [pullRequest(42)] })}
            />
        )

        await userEvent.click(screen.getByText('example/app'))

        expect(Array.from(container.querySelectorAll('dt'), (dt) => dt.textContent)).toEqual([
            'Report status',
            'Priority',
            'Pull requests',
            'Repository',
        ])
    })

    it('selects a pull request from its line when the report has several', async () => {
        const onSelectPullRequest = jest.fn()
        render(
            <ReportStatusSection
                report={makeReport({ repo_slug: 'example/app', pull_requests: [pullRequest(1), pullRequest(2)] })}
                selectedPullRequestUrl={pullRequest(1).url}
                onSelectPullRequest={onSelectPullRequest}
            />
        )

        expect(screen.getByLabelText('Show #1 in this report')).toHaveAttribute('aria-pressed', 'true')
        await userEvent.click(screen.getByLabelText('Show #2 in this report'))

        expect(onSelectPullRequest).toHaveBeenCalledWith(pullRequest(2).url)
        expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    })

    it('does not offer selection for a single pull request', () => {
        render(
            <ReportStatusSection
                report={makeReport({ repo_slug: 'example/app', pull_requests: [pullRequest(1)] })}
                selectedPullRequestUrl={pullRequest(1).url}
                onSelectPullRequest={() => {}}
            />
        )

        expect(screen.getByText('#1')).toBeInTheDocument()
        expect(screen.queryByLabelText('Show #1 in this report')).not.toBeInTheDocument()
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
                        responsible_user: null,
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
