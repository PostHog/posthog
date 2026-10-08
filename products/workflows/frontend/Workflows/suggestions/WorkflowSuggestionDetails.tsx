import { useValues } from 'kea'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'

import type { WorkflowProposalApi } from '../../generated/api.schemas'
import { workflowLogic } from '../workflowLogic'
import { SuggestedFieldChange, describeSuggestedChanges } from './suggestionChanges'
import { WorkflowSuggestionFieldDiff } from './WorkflowSuggestionFieldDiff'

function FieldDiffs({ fields }: { fields: SuggestedFieldChange[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-3 pl-2 border-l">
            {fields.map((change) => (
                <WorkflowSuggestionFieldDiff key={change.path} change={change} />
            ))}
        </div>
    )
}

export function WorkflowSuggestionDetails({
    id,
    proposal,
}: {
    id: string
    proposal: WorkflowProposalApi
}): JSX.Element {
    const { originalWorkflow } = useValues(workflowLogic({ id }))
    const changes = describeSuggestedChanges(proposal.content, originalWorkflow)
    const nothingToShow = changes.steps.length === 0 && changes.workflow.length === 0

    return (
        <div className="flex flex-col gap-3 text-sm">
            {nothingToShow && <span className="text-secondary">This suggestion changes nothing on the workflow.</span>}
            {changes.steps.map((step) => (
                <div key={step.stepId} className="flex flex-col gap-1">
                    <span className="font-semibold">
                        {step.stepName ? `Step: ${step.stepName}` : `New step: ${step.stepId}`}
                    </span>
                    <FieldDiffs fields={step.fields} />
                </div>
            ))}
            {changes.workflow.length > 0 && (
                <div className="flex flex-col gap-1">
                    <span className="font-semibold">Workflow</span>
                    <FieldDiffs fields={changes.workflow} />
                </div>
            )}
            <LemonCollapse
                size="xsmall"
                panels={[
                    {
                        key: 'raw',
                        header: 'Raw details',
                        content: (
                            <div className="flex flex-col gap-2">
                                <pre className="text-xs bg-surface-secondary rounded p-2 overflow-x-auto mb-0">
                                    {JSON.stringify(proposal.evidence, null, 2)}
                                </pre>
                                {proposal.source_id && (
                                    <div>
                                        <span className="font-semibold">Scout run: </span>
                                        {proposal.source_id}
                                    </div>
                                )}
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
