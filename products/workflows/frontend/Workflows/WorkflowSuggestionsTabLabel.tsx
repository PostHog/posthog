import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsTabLabel({ id }: { id: string }): JSX.Element {
    const { pendingProposals, optimisation, optimisationEnabled } = useValues(workflowProposalsLogic({ id }))

    return (
        <span className="flex items-center gap-1.5">
            Suggestions
            <LemonTag type="completion" size="small">
                Beta
            </LemonTag>
            {pendingProposals.length > 0 ? (
                <LemonTag type="completion" size="small">
                    {pendingProposals.length}
                </LemonTag>
            ) : (
                // Only once the setting has loaded: a tab that says "Off" for a moment on every open would mislead.
                optimisation !== null &&
                !optimisationEnabled && (
                    <LemonTag type="muted" size="small">
                        Off
                    </LemonTag>
                )
            )}
        </span>
    )
}
