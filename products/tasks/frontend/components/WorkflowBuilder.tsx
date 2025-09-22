import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlus, IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDialog, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { AgentDefinition, TaskWorkflow, WorkflowStage } from '../types'
import { workflowBuilderLogic } from './workflowBuilderLogic'

interface WorkflowBuilderProps {
    workflow?: TaskWorkflow
    onSave: (workflow: TaskWorkflow) => void
    onCancel: () => void
}

export function WorkflowBuilder({ workflow, onSave, onCancel }: WorkflowBuilderProps): JSX.Element {
    const logic = workflowBuilderLogic({ workflow })
    const {
        workflowName,
        workflowDescription,
        workflowColor,
        stages,
        agents,
        isValid,
        savedWorkflow,
        deletedWorkflow,
    } = useValues(logic)
    const {
        setWorkflowName,
        setWorkflowDescription,
        setWorkflowColor,
        addStage,
        removeStage,
        updateStage,
        saveWorkflow,
        deleteWorkflow,
    } = useActions(logic)

    const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

    useEffect(() => {
        if (savedWorkflow) {
            onSave(savedWorkflow)
        }
    }, [savedWorkflow, onSave])

    useEffect(() => {
        if (deletedWorkflow) {
            onCancel()
        }
    }, [deletedWorkflow, onCancel])

    return (
        <div className="space-y-6">
            {/* Workflow Metadata */}
            <LemonCard className="p-6">
                <h2 className="text-xl font-semibold mb-4">{workflow ? 'Edit Workflow' : 'Create New Workflow'}</h2>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                        <label className="block text-sm font-medium mb-1">Workflow Name</label>
                        <LemonInput value={workflowName} onChange={setWorkflowName} placeholder="Enter workflow name" />
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">Description</label>
                        <LemonInput
                            value={workflowDescription}
                            onChange={setWorkflowDescription}
                            placeholder="Describe this workflow"
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium mb-1">Workflow Color</label>
                        <input
                            type="color"
                            value={workflowColor}
                            onChange={(e) => setWorkflowColor(e.target.value)}
                            className="w-full h-10 border border-border rounded cursor-pointer"
                        />
                    </div>
                </div>
            </LemonCard>

            {/* Stages */}
            <LemonCard className="p-6">
                <div className="flex justify-between items-center mb-4">
                    <div>
                        <h3 className="text-lg font-medium">Workflow Stages</h3>
                        <p className="text-sm text-muted mt-1">
                            All workflows start with "Input" and end with "Complete". Add stages in between as needed.
                        </p>
                    </div>
                    <LemonButton type="secondary" icon={<IconPlus />} onClick={addStage}>
                        Add Stage
                    </LemonButton>
                </div>

                <div className="space-y-4">
                    {stages.map((stage, index) => (
                        <StageEditor
                            key={stage.id}
                            stage={stage}
                            position={index + 1}
                            agents={agents}
                            onUpdate={(updates) => updateStage(stage.id, updates)}
                            onRemove={() => removeStage(stage.id)}
                            isLast={index === stages.length - 1}
                            isFirst={index === 0}
                        />
                    ))}

                    {stages.length === 0 && (
                        <div className="text-center py-8 text-muted">
                            No stages defined. Add a stage to get started.
                        </div>
                    )}
                </div>
            </LemonCard>

            {/* Actions */}
            <div className="flex justify-between">
                {workflow && (
                    <LemonButton
                        type="secondary"
                        status="danger"
                        icon={<IconTrash />}
                        onClick={() => setShowDeleteConfirm(true)}
                    >
                        Delete Workflow
                    </LemonButton>
                )}
                <div className="flex gap-2 ml-auto">
                    <LemonButton type="secondary" onClick={onCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => saveWorkflow()} disabled={!isValid}>
                        {workflow ? 'Update Workflow' : 'Create Workflow'}
                    </LemonButton>
                </div>
            </div>

            {showDeleteConfirm && (
                <LemonDialog
                    title="Delete Workflow?"
                    description={`Are you sure you want to delete "${workflowName}"? This will deactivate the workflow and migrate all tasks to the backlog.`}
                    primaryButton={{
                        children: 'Delete',
                        status: 'danger',
                        onClick: () => {
                            deleteWorkflow()
                            setShowDeleteConfirm(false)
                        },
                    }}
                    secondaryButton={{
                        children: 'Cancel',
                        onClick: () => setShowDeleteConfirm(false),
                    }}
                    onClose={() => setShowDeleteConfirm(false)}
                />
            )}
        </div>
    )
}

interface StageEditorProps {
    stage: WorkflowStage
    position: number
    agents: AgentDefinition[]
    onUpdate: (updates: Partial<WorkflowStage>) => void
    onRemove: () => void
    isLast: boolean
    isFirst: boolean
}

function StageEditor({ stage, position, agents, onUpdate, onRemove, isLast, isFirst }: StageEditorProps): JSX.Element {
    const [agent, setAgent] = useState<string>(stage.agent_name || 'no_agent')

    return (
        <div className="border border-border rounded-lg p-4">
            <div className="flex justify-between items-start mb-4">
                <div className="flex items-center gap-2">
                    <div className="w-6 h-6 rounded-full bg-border flex items-center justify-center text-xs font-bold">
                        {position}
                    </div>
                    <h4 className="font-medium">Stage {position}</h4>
                    {isLast && <span className="text-xs bg-border rounded px-2 py-1 text-muted">Required</span>}
                </div>
                {!(isFirst || isLast) && (
                    <LemonButton size="xsmall" type="secondary" icon={<IconX />} onClick={onRemove} />
                )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Stage Name */}
                <div>
                    <label className="block text-sm font-medium mb-1">Stage Name</label>
                    <LemonInput
                        value={stage.name}
                        onChange={(name) => onUpdate({ name })}
                        placeholder="e.g. Code Review"
                        disabled={isLast}
                    />
                </div>

                {/* Assigned Agent */}
                <div>
                    <label className="block text-sm font-medium mb-1">Assigned Agent</label>
                    {isLast ? (
                        <div className="h-10 px-3 py-2 border border-border rounded bg-bg-light text-muted text-sm flex items-center">
                            No agent - tasks complete here
                        </div>
                    ) : (
                        <LemonSelect
                            value={agent}
                            onChange={(value) => {
                                setAgent(value)
                                onUpdate({ agent_name: value === 'no_agent' ? undefined : value })
                            }}
                            options={[
                                { value: 'no_agent', label: 'No agent (manual only)' },
                                ...agents.map((a) => ({
                                    value: a.id,
                                    label: a.name,
                                })),
                            ]}
                            placeholder="Select an agent"
                        />
                    )}
                </div>
            </div>
            {isLast && (
                <div className="mt-3 p-3 bg-bg-light rounded border">
                    <p className="text-sm text-muted">
                        ✅ This is the final stage - tasks are marked as complete when they reach here.
                    </p>
                </div>
            )}
        </div>
    )
}
