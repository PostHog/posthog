import { useValues } from 'kea'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsTabLabel({ id }: { id: string }): JSX.Element {
    const { pendingProposals, optimisationEnabled } = useValues(workflowProposalsLogic({ id }))

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
                optimisationEnabled && (
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
