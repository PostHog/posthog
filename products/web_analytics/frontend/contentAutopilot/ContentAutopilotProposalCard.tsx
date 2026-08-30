import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import type { ContentAutopilotProposalListApi } from 'products/web_analytics/frontend/generated/api.schemas'

export interface ContentAutopilotProposalCardProps {
    proposal: ContentAutopilotProposalListApi
    onReview: (proposalId: string) => void
}

const statusLabel: Record<ContentAutopilotProposalListApi['lifecycle_status'], string> = {
    generating: 'Generating',
    ready_for_review: 'Ready for review',
    rejected: 'Rejected',
    exported: 'Exported',
    pr_opened: 'Pull request opened',
    failed: 'Failed',
}

export const ContentAutopilotProposalCard = ({
    proposal,
    onReview,
}: ContentAutopilotProposalCardProps): JSX.Element => {
    const primaryEvidence = proposal.evidence[0]

    return (
        <LemonCard hoverEffect={false} className="p-4 flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonTag type={proposal.validation_report.passed ? 'success' : 'danger'}>
                    {statusLabel[proposal.lifecycle_status]}
                </LemonTag>
                <span className="text-xs text-muted">{proposal.file_path}</span>
            </div>
            <div>
                <h3 className="m-0">{proposal.title}</h3>
                <p className="m-0 mt-1 text-muted">{proposal.target_query}</p>
            </div>
            {primaryEvidence ? (
                <div className="rounded border p-3 bg-surface-secondary">
                    <div className="font-semibold">Why PostHog selected this</div>
                    <div className="text-sm mt-1">{primaryEvidence.explanation}</div>
                </div>
            ) : null}
            <div className="flex justify-end mt-auto">
                <LemonButton type="secondary" onClick={() => onReview(proposal.id)}>
                    Review proposal
                </LemonButton>
            </div>
        </LemonCard>
    )
}
