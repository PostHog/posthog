import type { ContentAutopilotProposalListApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotProposalCard } from './ContentAutopilotProposalCard'

export interface ContentAutopilotProposalSectionProps {
    title: string
    description: string
    proposals: ContentAutopilotProposalListApi[]
    onReview: (proposalId: string) => void
}

export const ContentAutopilotProposalSection = ({
    title,
    description,
    proposals,
    onReview,
}: ContentAutopilotProposalSectionProps): JSX.Element | null => {
    if (proposals.length === 0) {
        return null
    }

    return (
        <section>
            <div className="mb-3">
                <h2 className="m-0">{title}</h2>
                <p className="m-0 mt-1 text-muted">{description}</p>
            </div>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                {proposals.map((proposal) => (
                    <ContentAutopilotProposalCard key={proposal.id} proposal={proposal} onReview={onReview} />
                ))}
            </div>
        </section>
    )
}
