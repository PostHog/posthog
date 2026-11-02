import { LemonTag, Spinner } from '@posthog/lemon-ui'

import type { ContentAutopilotProposalListApi } from 'products/web_analytics/frontend/generated/api.schemas'

export const ContentAutopilotProposalStatusTag = ({
    proposal,
}: {
    proposal: ContentAutopilotProposalListApi
}): JSX.Element => {
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
