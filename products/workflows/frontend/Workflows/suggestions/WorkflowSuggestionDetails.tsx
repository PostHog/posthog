import { useValues } from 'kea'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { WorkflowProposalApi } from '../../generated/api.schemas'
import { workflowLogic } from '../workflowLogic'
import { SuggestedFieldChange, describeSuggestedChanges, groupStepFields } from './suggestionChanges'
import { WorkflowSuggestionEmailChange } from './WorkflowSuggestionEmailChange'

function ChangedValue({ value }: { value: unknown }): JSX.Element {
    if (value === undefined) {
        return <span className="text-secondary italic">Not set</span>
    }
    if (value === null) {
        return <span className="text-secondary italic">Removed</span>
    }
    if (typeof value === 'string') {
        return <span className="whitespace-pre-wrap break-words line-clamp-4">{value}</span>
    }
    return (
        <pre className="text-xs bg-surface-secondary rounded p-2 overflow-x-auto mb-0 max-h-40">
            {JSON.stringify(value, null, 2)}
        </pre>
    )
}

const COLUMNS: LemonTableColumns<SuggestedFieldChange> = [
    {
        title: 'Field',
        key: 'field',
        width: '20%',
        render: (_, change) => (
            <Tooltip title={change.path}>
                <span className="font-medium">{change.label}</span>
            </Tooltip>
        ),
    },
    { title: 'Now', key: 'before', width: '40%', render: (_, change) => <ChangedValue value={change.before} /> },
    { title: 'Suggested', key: 'after', width: '40%', render: (_, change) => <ChangedValue value={change.after} /> },
]

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
            {changes.steps.map((step) => {
                const { email, main, other } = groupStepFields(step)
                return (
                    <div key={step.stepId} className="flex flex-col gap-1">
                        <span className="font-semibold">
                            {step.isNew
                                ? `New step: ${step.stepName ?? step.stepId}`
                                : `Step: ${step.stepName ?? step.stepId}`}
                        </span>
                        {main.length > 0 && (
                            <LemonTable size="small" columns={COLUMNS} dataSource={main} rowKey="path" />
                        )}
                        {email.map((change) => (
                            <WorkflowSuggestionEmailChange key={change.path} change={change} />
                        ))}
                        {other.length > 0 && (
                            <LemonCollapse
                                size="xsmall"
                                panels={[
                                    {
                                        key: 'other',
                                        header: `Other settings (${other.length})`,
                                        content: (
                                            <LemonTable
                                                size="small"
                                                columns={COLUMNS}
                                                dataSource={other}
                                                rowKey="path"
                                            />
                                        ),
                                    },
                                ]}
                            />
                        )}
                    </div>
                )
            })}
            {changes.workflow.length > 0 && (
                <div className="flex flex-col gap-1">
                    <span className="font-semibold">Workflow</span>
                    <LemonTable size="small" columns={COLUMNS} dataSource={changes.workflow} rowKey="path" />
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
