import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonTable, LemonTag, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { ContentAutopilotProposalListApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { contentAutopilotLogic } from './contentAutopilotLogic'

const proposalStatusTag = (proposal: ContentAutopilotProposalListApi): JSX.Element => {
    switch (proposal.lifecycle_status) {
        case 'ready_for_review':
            return <LemonTag type="success">Ready to review</LemonTag>
        case 'generating':
            return (
                <LemonTag type="completion" icon={<Spinner />}>
                    Drafting
                </LemonTag>
            )
        case 'exported':
            return <LemonTag type="default">Downloaded</LemonTag>
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

export const ContentAutopilotDrafts = (): JSX.Element | null => {
    const { draftRows, workspaceErrors } = useValues(contentAutopilotLogic)
    const { selectProposal, setWorkspaceTab } = useActions(contentAutopilotLogic)

    if (draftRows.length === 0 && workspaceErrors.proposals) {
        return null
    }

    if (draftRows.length === 0) {
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
            dataSource={draftRows}
            rowKey="id"
            columns={[
                {
                    title: 'Draft',
                    key: 'title',
                    render: (_, row) => (
                        <div className="py-2 min-w-60">
                            <div className="font-semibold">{row.title}</div>
                            {row.question ? <div className="text-xs text-muted mt-1">{row.question}</div> : null}
                        </div>
                    ),
                },
                {
                    title: 'Change',
                    key: 'change',
                    render: (_, row) => (
                        <div className="text-sm">
                            <div>{row.isNewPage ? 'New page' : 'Updates a page'}</div>
                            <div className="text-xs text-muted truncate max-w-80">{row.path}</div>
                        </div>
                    ),
                },
                {
                    title: 'Status',
                    key: 'status',
                    render: (_, row) =>
                        row.proposal ? proposalStatusTag(row.proposal) : <LemonTag type="muted">Queued</LemonTag>,
                },
                {
                    title: 'Updated',
                    key: 'updated',
                    render: (_, row) => <TZLabel time={row.updatedAt} />,
                },
                {
                    key: 'actions',
                    render: (_, { proposal }) =>
                        proposal && proposal.lifecycle_status !== 'generating' ? (
                            <div className="flex justify-end">
                                <LemonButton
                                    size="small"
                                    type={proposal.lifecycle_status === 'ready_for_review' ? 'primary' : 'secondary'}
                                    onClick={() => selectProposal(proposal.id)}
                                    data-attr="content-autopilot-review-draft"
                                >
                                    Review
                                </LemonButton>
                            </div>
                        ) : null,
                },
            ]}
        />
    )
}
