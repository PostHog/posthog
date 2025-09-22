import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconInfo, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TaskWorkflow } from '../types'
import { WorkflowBuilder } from './WorkflowBuilder'
import { workflowSettingsLogic } from './workflowSettingsLogic'

export function WorkflowSettings(): JSX.Element {
    const { workflows, loading, selectedWorkflow } = useValues(workflowSettingsLogic)
    const { loadWorkflows, selectWorkflow, deleteWorkflow } = useActions(workflowSettingsLogic)
    const [showCreateForm, setShowCreateForm] = useState(false)
    const [editingWorkflow, setEditingWorkflow] = useState<TaskWorkflow | null>(null)

    if (loading) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="h-8 w-64" />
                <LemonSkeleton className="h-32 w-full" />
                <LemonSkeleton className="h-32 w-full" />
            </div>
        )
    }

    // Show workflow builder when creating or editing
    if (showCreateForm || editingWorkflow) {
        return (
            <WorkflowBuilder
                workflow={editingWorkflow || undefined}
                onSave={(workflow) => {
                    setShowCreateForm(false)
                    setEditingWorkflow(null)
                    loadWorkflows()
                    selectWorkflow(workflow.id)
                }}
                onCancel={() => {
                    setShowCreateForm(false)
                    setEditingWorkflow(null)
                }}
            />
        )
    }

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h2 className="text-xl font-semibold">Workflow Configuration</h2>
                    <p className="text-muted text-sm mt-1">
                        Configure custom workflows to define how tasks move through different stages
                    </p>
                </div>
                <LemonButton type="secondary" icon={<IconPlus />} onClick={() => setShowCreateForm(true)}>
                    New Workflow
                </LemonButton>
            </div>

            {workflows.length === 0 ? (
                <LemonCard className="p-8 text-center">
                    <IconInfo className="w-12 h-12 text-muted mx-auto mb-4" />
                    <h3 className="text-lg font-medium mb-2">No Workflows Configured</h3>
                    <p className="text-muted mb-4">Creating default workflow...</p>
                </LemonCard>
            ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {workflows.map((workflow) => (
                        <WorkflowCard
                            key={workflow.id}
                            workflow={workflow}
                            onSelect={() => selectWorkflow(workflow.id)}
                            onDelete={() => deleteWorkflow(workflow.id)}
                            isSelected={selectedWorkflow?.id === workflow.id}
                        />
                    ))}
                </div>
            )}

            {selectedWorkflow && (
                <div className="mt-8">
                    <WorkflowDetailView />
                </div>
            )}
        </div>
    )
}

interface WorkflowCardProps {
    workflow: TaskWorkflow
    onSelect: () => void
    onDelete: () => void
    isSelected: boolean
}

function WorkflowCard({ workflow, onSelect, onDelete, isSelected }: WorkflowCardProps): JSX.Element {
    return (
        <LemonCard
            className={`p-4 cursor-pointer transition-all ${isSelected ? 'ring-2 ring-primary' : ''}`}
            hoverEffect={true}
            onClick={onSelect}
        >
            <div className="flex justify-between items-start mb-2">
                <div className="flex items-center gap-2">
                    <h3 className="font-medium">{workflow.name}</h3>
                    {workflow.is_default && (
                        <LemonTag type="primary" size="small">
                            Default
                        </LemonTag>
                    )}
                </div>
                <div className="flex items-center gap-1">
                    {workflow.can_delete.can_delete && (
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={<IconX />}
                            onClick={(e) => {
                                e.stopPropagation()
                                onDelete()
                            }}
                            tooltip="Delete workflow"
                        />
                    )}
                </div>
            </div>

            <p className="text-sm text-muted mb-3">{workflow.description}</p>

            <div className="flex justify-between items-center text-xs text-muted">
                <span>{workflow.stages.length} stages</span>
                <span>{workflow.task_count} tasks</span>
            </div>

            <div className="flex gap-1 mt-2">
                {workflow.stages.slice(0, 5).map((stage) => (
                    <div
                        key={stage.id}
                        className="h-2 flex-1 rounded"
                        style={{ backgroundColor: stage.color }}
                        title={stage.name}
                    />
                ))}
                {workflow.stages.length > 5 && <div className="text-xs text-muted">+{workflow.stages.length - 5}</div>}
            </div>
        </LemonCard>
    )
}

function WorkflowDetailView(): JSX.Element {
    const { selectedWorkflow } = useValues(workflowSettingsLogic)
    const [editingWorkflow, setEditingWorkflow] = useState<TaskWorkflow | null>(null)

    if (!selectedWorkflow) {
        return <div />
    }

    // Show workflow builder when editing
    if (editingWorkflow) {
        return (
            <WorkflowBuilder
                workflow={editingWorkflow}
                onSave={() => {
                    setEditingWorkflow(null)
                    // Refresh workflows list
                    window.location.reload()
                }}
                onCancel={() => setEditingWorkflow(null)}
            />
        )
    }
    return (
        <LemonCard className="p-6">
            <div className="flex justify-between items-start mb-4">
                <div>
                    <h3 className="text-lg font-semibold">{selectedWorkflow.name}</h3>
                    <p className="text-muted">{selectedWorkflow.description}</p>
                </div>
                <LemonButton type="primary" size="small" onClick={() => setEditingWorkflow(selectedWorkflow)}>
                    Edit Workflow
                </LemonButton>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div>
                    <h4 className="font-medium mb-3">Stages ({selectedWorkflow.stages.length})</h4>
                    <div className="space-y-2">
                        {selectedWorkflow.stages.map((stage) => (
                            <div key={stage.id} className="flex items-center gap-3 p-2 bg-bg-light rounded">
                                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: stage.color }} />
                                <span className="flex-1">{stage.name}</span>
                                <span className="text-xs text-muted">{stage.task_count} tasks</span>
                                {stage.is_manual_only && <LemonTag size="small">Manual</LemonTag>}
                            </div>
                        ))}
                    </div>
                </div>

                <div>
                    <h4 className="font-medium mb-3">Workflow Flow</h4>
                    <div className="space-y-2">
                        <div className="p-3 bg-bg-light rounded text-sm">
                            <div className="text-center text-muted">
                                <p className="mb-2">Linear workflow progression:</p>
                                <div className="flex items-center justify-center gap-2">
                                    {selectedWorkflow.stages.map((stage, index) => (
                                        <div key={stage.id} className="flex items-center">
                                            <span className="text-xs px-2 py-1 bg-white rounded border">
                                                {stage.name}
                                            </span>
                                            {index < selectedWorkflow.stages.length - 1 && (
                                                <span className="mx-2">→</span>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </LemonCard>
    )
}
