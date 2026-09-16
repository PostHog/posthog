import { useActions, useValues } from 'kea'

import { LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { WorkflowAppliedOutcome } from './WorkflowAppliedOutcome'
import { workflowLogic } from './workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'
import { WorkflowSuggestionCard } from './WorkflowSuggestionCard'

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
    const { setOptimisationEnabled } = useActions(workflowProposalsLogic({ id }))
    const { workflowUserAccessLevel } = useValues(workflowLogic({ id }))

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
        return (
            <div className="flex flex-col gap-2 items-start">
                <h3 className="mb-0">Suggestions are off for this workflow</h3>
                <p className="mb-0 text-secondary">
                    Turn on "Suggest improvements" to have PostHog read how this workflow performs and suggest changes.
                    Only the workflows you turn on are read, and nothing changes until you approve a suggestion and
                    publish it.
                </p>
                <AccessControlAction
                    resourceType={AccessControlResourceType.Workflow}
                    minAccessLevel={AccessControlLevel.Editor}
                    userAccessLevel={workflowUserAccessLevel ?? undefined}
                >
                    {({ disabledReason }) => (
                        <LemonSwitch
                            bordered
                            label="Suggest improvements"
                            checked={optimisationEnabled}
                            disabled={optimisationLoading || !!disabledReason}
                            tooltip={disabledReason}
                            onChange={(checked) => setOptimisationEnabled(checked)}
                            data-attr="workflow-suggestions-enable"
                        />
                    )}
                </AccessControlAction>
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
