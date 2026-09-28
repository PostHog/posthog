import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsTabLabel({ id }: { id: string }): JSX.Element {
    const { pendingProposals } = useValues(workflowProposalsLogic({ id }))

    return (
        <span className="flex items-center gap-1.5">
            Suggestions
            {pendingProposals.length > 0 && (
                <LemonTag type="completion" size="small">
                    {pendingProposals.length}
                </LemonTag>
            )}
        </span>
    )
}
