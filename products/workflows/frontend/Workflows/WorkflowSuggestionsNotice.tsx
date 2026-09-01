import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { urls } from 'scenes/urls'

import { workflowProposalsLogic } from './workflowProposalsLogic'

/** One line above the tabs, so a suggestion is noticed without taking the editor's space. */
export function WorkflowSuggestionsNotice({ id }: { id: string }): JSX.Element | null {
    const { pendingProposals } = useValues(workflowProposalsLogic({ id }))

    if (pendingProposals.length === 0) {
        return null
    }

    return (
        <LemonBanner
            type="info"
            action={{
                children: 'Review',
                'data-attr': 'workflow-suggestions-review',
                onClick: () => router.actions.push(urls.workflow(id, 'suggestions')),
            }}
        >
            {pendingProposals.length === 1
                ? 'PostHog suggests a change to this workflow.'
                : `PostHog suggests ${pendingProposals.length} changes to this workflow.`}
        </LemonBanner>
    )
}
