import type { WorkflowProposalApi } from '../generated/api.schemas'

export function WorkflowSuggestionDetails({ proposal }: { proposal: WorkflowProposalApi }): JSX.Element {
    const changedFields = Object.keys(proposal.content)

    return (
        <div className="flex flex-col gap-2 text-sm">
            <div>
                <span className="font-semibold">Workflow fields it changes: </span>
                {changedFields.length ? changedFields.join(', ') : 'none'}
            </div>
            <div className="flex flex-col gap-1">
                <span className="font-semibold">Evidence</span>
                <pre className="text-xs bg-surface-secondary rounded p-2 overflow-x-auto mb-0">
                    {JSON.stringify(proposal.evidence, null, 2)}
                </pre>
            </div>
            {proposal.source_id && (
                <div>
                    <span className="font-semibold">Source: </span>
                    {proposal.source_id}
                </div>
            )}
        </div>
    )
}
