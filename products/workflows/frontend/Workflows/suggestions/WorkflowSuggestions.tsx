import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { WorkflowAppliedOutcome } from './WorkflowAppliedOutcome'
import { workflowProposalsLogic } from './workflowProposalsLogic'
import { WorkflowStagedSuggestion } from './WorkflowStagedSuggestion'
import { WorkflowSuggestionCard } from './WorkflowSuggestionCard'
import { WorkflowSuggestionsIntroduction } from './WorkflowSuggestionsIntroduction'
import { WorkflowSuggestionsSwitch } from './WorkflowSuggestionsSwitch'

function SuggestionsOffNotice(): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <h3 className="mb-0">Suggestions are off for this workflow</h3>
            <p className="mb-0 text-secondary">
                Turn on "Suggest improvements" in the workflow menu to have PostHog read how this workflow performs and
                suggest changes. Only the workflows you turn on are read.
            </p>
        </div>
    )
}

export function WorkflowSuggestions({ id }: { id: string }): JSX.Element {
    const {
        pendingProposals,
        approvedProposals,
        appliedProposals,
        outcomes,
        optimisationEnabled,
        optimisation,
        optimisationLoading,
        optimisationUnreadable,
        proposalsResponse,
        approvedResponse,
        appliedResponse,
        proposalsResponseLoading,
        approvedResponseLoading,
        appliedResponseLoading,
    } = useValues(workflowProposalsLogic({ id }))

    const measuredApplied = appliedProposals.filter((proposal) => outcomes[proposal.id]?.after)
    // Each list answers separately; "nothing here" is unknown until all have.
    const listsUnknown = proposalsResponse === null || approvedResponse === null || appliedResponse === null
    const listsSettling =
        proposalsResponseLoading ||
        approvedResponseLoading ||
        appliedResponseLoading ||
        appliedProposals.some((proposal) => !outcomes[proposal.id])

    if ((optimisation === null && optimisationLoading) || (optimisationEnabled && listsUnknown)) {
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

    const nothingFiled = pendingProposals.length === 0 && approvedProposals.length === 0 && measuredApplied.length === 0

    // Off with nothing filed is the introduction; off with a queue still shows the queue, since the
    // server keeps those resolvable.
    if (!optimisationEnabled && nothingFiled) {
        return <WorkflowSuggestionsIntroduction id={id} enabled={false} />
    }

    if (optimisationEnabled && nothingFiled && !listsSettling) {
        return <WorkflowSuggestionsIntroduction id={id} enabled />
    }

    return (
        <div className="flex flex-col gap-4">
            {/* Turning suggestions off leaves what was already filed for someone to resolve. */}
            {!optimisationEnabled && <SuggestionsOffNotice />}
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
            {approvedProposals.length > 0 && (
                <div className="flex flex-col gap-2">
                    <h3 className="mb-0">Staged as draft</h3>
                    {approvedProposals.map((proposal) => (
                        <WorkflowStagedSuggestion key={proposal.id} id={id} proposal={proposal} />
                    ))}
                </div>
            )}
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
