import { useValues } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { workflowLogic } from '../workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsTabLabel({ id }: { id: string }): JSX.Element {
    const { pendingProposals, optimizationEnabled } = useValues(workflowProposalsLogic({ id }))
    const { workflow } = useValues(workflowLogic({ id }))
    // Archiving leaves the opt-in row enabled, and nothing is watched any more, so the row alone
    // would keep saying "On" for a workflow that cannot produce a suggestion.
    const watching = optimizationEnabled && workflow?.status === 'active'

    return (
        <span className="flex items-center gap-1.5">
            Self-driving
            <LemonTag type="completion" size="small">
                Beta
            </LemonTag>
            {pendingProposals.length > 0 ? (
                <LemonTag type="completion" size="small">
                    {pendingProposals.length}
                </LemonTag>
            ) : (
                watching && (
                    <Tooltip title="PostHog is watching this workflow and will suggest changes here.">
                        <LemonTag type="option" size="small">
                            On
                        </LemonTag>
                    </Tooltip>
                )
            )}
        </span>
    )
}
