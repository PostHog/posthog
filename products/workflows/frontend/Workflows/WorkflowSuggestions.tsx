import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { WorkflowAppliedOutcome } from './WorkflowAppliedOutcome'
import { workflowProposalsLogic } from './workflowProposalsLogic'
import { WorkflowSuggestionCard } from './WorkflowSuggestionCard'
import { WorkflowSuggestionsIntroduction } from './WorkflowSuggestionsIntroduction'
import { WorkflowSuggestionsSwitch } from './WorkflowSuggestionsSwitch'

export function WorkflowSuggestions({ id }: { id: string }): JSX.Element {
    const {
        pendingProposals,
        appliedProposals,
        outcomes,
        optimisationEnabled,
        optimisation,
        optimisationLoading,
        optimisationUnreadable,
    } = useValues(workflowProposalsLogic({ id }))

    const measuredApplied = appliedProposals.filter((proposal) => outcomes[proposal.id]?.after)

    if (optimisation === null && optimisationLoading) {
        return <Spinner />
    }

    if (optimisationUnreadable) {
        return (
            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Could not read this workflow's suggestion setting</h3>
                <p className="mb-0 text-secondary">
                    Reload the page to try again. Nothing changed: whatever the setting was, it still is.
                </p>
            </div>
        )
    }

    if (!optimisationEnabled) {
        return <WorkflowSuggestionsIntroduction id={id} enabled={false} />
    }

    if (pendingProposals.length === 0 && measuredApplied.length === 0) {
        return <WorkflowSuggestionsIntroduction id={id} enabled />
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                    <h3 className="mb-0">Waiting for you</h3>
                    <WorkflowSuggestionsSwitch id={id} />
                </div>
                {pendingProposals.length === 0 ? (
                    <p className="mb-0 text-secondary">
                        Nothing to review. PostHog reads this workflow's metrics on a schedule and files a suggestion
                        here when it finds a change worth making. Nothing reaches anyone until you approve a suggestion
                        and publish it.
                    </p>
                ) : (
                    pendingProposals.map((proposal) => (
                        <WorkflowSuggestionCard key={proposal.id} id={id} proposal={proposal} />
                    ))
                )}
            </div>
            {measuredApplied.length > 0 && (
                <div className="flex flex-col gap-2">
                    <h3 className="mb-0">Applied</h3>
                    {measuredApplied.map((proposal) => (
                        <WorkflowAppliedOutcome key={proposal.id} proposal={proposal} outcome={outcomes[proposal.id]} />
                    ))}
                </div>
            )}
        </div>
    )
}
