import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { WorkflowAppliedOutcome } from './WorkflowAppliedOutcome'
import { workflowProposalsLogic } from './workflowProposalsLogic'
import { WorkflowSuggestionCard } from './WorkflowSuggestionCard'

export function WorkflowSuggestions({ id }: { id: string }): JSX.Element {
    const { pendingProposals, appliedProposals, outcomes, optimisationEnabled, optimisation, optimisationLoading } =
        useValues(workflowProposalsLogic({ id }))

    const measuredApplied = appliedProposals.filter((proposal) => outcomes[proposal.id]?.after)

    if (optimisation === null && optimisationLoading) {
        return <Spinner />
    }

    if (!optimisationEnabled) {
        return (
            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Suggestions are off for this workflow</h3>
                <p className="mb-0 text-secondary">
                    Turn on "Suggest improvements" in the workflow menu to have PostHog read how this workflow performs
                    and suggest changes. Only the workflows you turn on are read.
                </p>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Waiting for you</h3>
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
