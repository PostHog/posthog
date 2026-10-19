import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonTable, LemonTag, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { parseWebAnalyticsURL } from 'scenes/web-analytics/common'

import type { ContentAutopilotProposalListApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotDraftRow, contentAutopilotLogic } from './contentAutopilotLogic'

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

const proposalPath = (proposal: ContentAutopilotProposalListApi): string =>
    proposal.file_path ? `/${proposal.file_path.replace(/\.mdx?$/, '')}` : ''

const rowTitle = (row: ContentAutopilotDraftRow): string =>
    row.kind === 'proposal' ? row.proposal.title : row.opportunity.title

const rowQuestion = (row: ContentAutopilotDraftRow): string =>
    row.kind === 'proposal' ? row.proposal.target_query : ''

const rowIsNewPage = (row: ContentAutopilotDraftRow): boolean =>
    row.kind === 'proposal'
        ? row.proposal.proposal_type === 'new_content'
        : row.opportunity.recommended_type === 'new_content'

const rowPath = (row: ContentAutopilotDraftRow): string =>
    row.kind === 'proposal'
        ? proposalPath(row.proposal)
        : row.opportunity.target_url
          ? (parseWebAnalyticsURL(row.opportunity.target_url).pathname ?? '')
          : ''

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
                            <div className="font-semibold">{rowTitle(row)}</div>
                            {rowQuestion(row) ? (
                                <div className="text-xs text-muted mt-1">{rowQuestion(row)}</div>
                            ) : null}
                        </div>
                    ),
                },
                {
                    title: 'Change',
                    key: 'change',
                    render: (_, row) => (
                        <div className="text-sm">
                            <div>{rowIsNewPage(row) ? 'New page' : 'Updates a page'}</div>
                            <div className="text-xs text-muted truncate max-w-80">{rowPath(row)}</div>
                        </div>
                    ),
                },
                {
                    title: 'Status',
                    key: 'status',
                    render: (_, row) =>
                        row.kind === 'proposal' ? (
                            proposalStatusTag(row.proposal)
                        ) : (
                            <LemonTag type="muted">Queued</LemonTag>
                        ),
                },
                {
                    title: 'Updated',
                    key: 'updated',
                    render: (_, row) => (
                        <TZLabel
                            time={row.kind === 'proposal' ? row.proposal.updated_at : row.opportunity.updated_at}
                        />
                    ),
                },
                {
                    key: 'actions',
                    render: (_, row) =>
                        row.kind === 'proposal' && row.proposal.lifecycle_status !== 'generating' ? (
                            <div className="flex justify-end">
                                <LemonButton
                                    size="small"
                                    type={
                                        row.proposal.lifecycle_status === 'ready_for_review' ? 'primary' : 'secondary'
                                    }
                                    onClick={() => selectProposal(row.proposal.id)}
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
