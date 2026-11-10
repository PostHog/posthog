import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import type { ContentAutopilotOpportunityApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { contentAutopilotLogic } from './contentAutopilotLogic'

export const ContentAutopilotDraftButton = ({
    opportunity,
    onReview,
}: {
    opportunity: ContentAutopilotOpportunityApi
    onReview?: () => void
}): JSX.Element | null => {
    const { rowDraftDisabledReason, runMutationLoading, draftingOpportunityIds, opportunityProposals } =
        useValues(contentAutopilotLogic)
    const { draftOpportunities, selectProposal } = useActions(contentAutopilotLogic)

    if (opportunity.status === 'new') {
        return (
            <LemonButton
                size="small"
                type="secondary"
                onClick={() => draftOpportunities([opportunity.id])}
                loading={runMutationLoading && draftingOpportunityIds.includes(opportunity.id)}
                disabledReason={rowDraftDisabledReason}
                data-attr="content-autopilot-draft-opportunity"
            >
                {opportunity.recommended_type === 'page_improvement' ? 'Draft changes' : 'Draft page'}
            </LemonButton>
        )
    }

    const proposalId = opportunity.proposal_id
    if (
        proposalId &&
        opportunity.status === 'drafted' &&
        opportunityProposals[opportunity.id]?.lifecycle_status !== 'generating'
    ) {
        return (
            <LemonButton
                size="small"
                type="secondary"
                onClick={() => {
                    onReview?.()
                    selectProposal(proposalId)
                }}
                data-attr="content-autopilot-review-opportunity-draft"
            >
                Review draft
            </LemonButton>
        )
    }

    return null
}
