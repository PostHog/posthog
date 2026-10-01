import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { ContentAutopilotProposalListApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { contentAutopilotLogic } from './contentAutopilotLogic'

const statusTag = (proposal: ContentAutopilotProposalListApi): JSX.Element => {
    switch (proposal.lifecycle_status) {
        case 'ready_for_review':
            return <LemonTag type="success">Ready to review</LemonTag>
        case 'generating':
            return <LemonTag type="completion">Drafting</LemonTag>
        case 'exported':
            return <LemonTag type="primary">Downloaded</LemonTag>
        case 'rejected':
            return <LemonTag type="muted">Rejected</LemonTag>
        case 'failed':
            return proposal.validation_report.checks.some(
                ({ check_key, passed }) => check_key === 'generation' && !passed
            ) ? (
                <LemonTag type="danger">Couldn't draft</LemonTag>
            ) : (
                <LemonTag type="warning">Needs fixes</LemonTag>
            )
    }
}

const pagePath = (proposal: ContentAutopilotProposalListApi): string =>
    proposal.file_path ? `/${proposal.file_path.replace(/\.mdx?$/, '')}` : ''

export const ContentAutopilotDrafts = (): JSX.Element | null => {
    const { reviewQueue, workspaceErrors } = useValues(contentAutopilotLogic)
    const { selectProposal, setWorkspaceTab } = useActions(contentAutopilotLogic)

    if (reviewQueue.length === 0 && workspaceErrors.proposals) {
        return null
    }

    if (reviewQueue.length === 0) {
        return (
            <LemonCard hoverEffect={false} className="p-8 text-center">
                <h3 className="m-0">No drafts yet</h3>
                <p className="m-0 mt-2 text-muted max-w-xl mx-auto">
                    Pick questions on the Opportunities tab and draft them. Drafts show up here for review.
                </p>
                <LemonButton
                    type="secondary"
                    className="mt-4 mx-auto"
                    onClick={() => setWorkspaceTab('opportunities')}
                    data-attr="content-autopilot-drafts-empty-opportunities"
                >
                    Go to opportunities
                </LemonButton>
            </LemonCard>
        )
    }

    return (
        <LemonTable
            dataSource={reviewQueue}
            rowKey="id"
            columns={[
                {
                    title: 'Draft',
                    key: 'title',
                    render: (_, proposal) => (
                        <div className="py-2 min-w-60">
                            <div className="font-semibold">{proposal.title}</div>
                            <div className="text-xs text-muted mt-1">{proposal.target_query}</div>
                        </div>
                    ),
                },
                {
                    title: 'Change',
                    key: 'change',
                    render: (_, proposal) => (
                        <div className="text-sm">
                            <div>{proposal.proposal_type === 'new_content' ? 'New page' : 'Updates a page'}</div>
                            <div className="text-xs text-muted truncate max-w-80">{pagePath(proposal)}</div>
                        </div>
                    ),
                },
                {
                    title: 'Status',
                    key: 'status',
                    render: (_, proposal) => statusTag(proposal),
                },
                {
                    title: 'Updated',
                    key: 'updated',
                    render: (_, proposal) => <TZLabel time={proposal.updated_at} />,
                },
                {
                    key: 'actions',
                    render: (_, proposal) => (
                        <div className="flex justify-end">
                            <LemonButton
                                size="small"
                                type={proposal.lifecycle_status === 'ready_for_review' ? 'primary' : 'secondary'}
                                onClick={() => selectProposal(proposal.id)}
                                disabledReason={
                                    proposal.lifecycle_status === 'generating'
                                        ? 'This draft is still being written'
                                        : undefined
                                }
                                data-attr="content-autopilot-review-draft"
                            >
                                Review
                            </LemonButton>
                        </div>
                    ),
                },
            ]}
        />
    )
}
