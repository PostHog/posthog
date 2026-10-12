import { useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { workflowProposalsLogic } from '../suggestions/workflowProposalsLogic'
import { workflowLogic } from '../workflowLogic'

const MAX_SUGGESTIONS = 3

export function WorkflowOverviewSuggestions({ id }: { id: string }): JSX.Element {
    const { pendingProposals, optimizationEnabled } = useValues(workflowProposalsLogic({ id }))
    const { workflow } = useValues(workflowLogic({ id }))
    const selfDrivingUrl = urls.workflow(id, 'self-driving')
    const watching = optimizationEnabled && workflow?.status === 'active'

    return (
        <div
            className="flex flex-col gap-3 rounded border bg-surface-primary p-4"
            data-attr="workflow-overview-suggestions"
        >
            <div className="flex items-center justify-between gap-2">
                <h3 className="mb-0 flex items-center gap-2 text-base font-semibold">
                    Suggested changes
                    {pendingProposals.length > 0 ? (
                        <LemonTag type="completion" size="small">
                            {pendingProposals.length}
                        </LemonTag>
                    ) : null}
                </h3>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    sideIcon={<IconChevronRight />}
                    to={selfDrivingUrl}
                    data-attr="workflow-overview-suggestions-open"
                >
                    {pendingProposals.length > 0 ? 'Review' : 'Open'}
                </LemonButton>
            </div>
            {pendingProposals.length > 0 ? (
                <div className="flex flex-col gap-1 text-sm">
                    {pendingProposals.slice(0, MAX_SUGGESTIONS).map((proposal) => (
                        <Link
                            key={proposal.id}
                            to={selfDrivingUrl}
                            className="truncate"
                            data-attr="workflow-overview-suggestion"
                        >
                            {proposal.title}
                        </Link>
                    ))}
                    {pendingProposals.length > MAX_SUGGESTIONS ? (
                        <span className="text-xs text-muted">And {pendingProposals.length - MAX_SUGGESTIONS} more</span>
                    ) : null}
                </div>
            ) : watching ? (
                <span className="text-sm text-muted">
                    No suggestions yet. PostHog is watching this workflow and will suggest changes here.
                </span>
            ) : (
                <span className="text-sm text-muted">
                    Turn on self-driving to get suggested changes based on how this workflow performs.
                </span>
            )}
        </div>
    )
}
