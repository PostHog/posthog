import { useState } from 'react'

import { LemonButton, LemonCard, LemonSelect, Link } from '@posthog/lemon-ui'

import { IconBranch, IconGithub } from 'lib/lemon-ui/icons'

import { ORIGIN_PRODUCT_COLORS, ORIGIN_PRODUCT_LABELS } from '../constants'
import { Task, TaskWorkflow } from '../types'

interface TaskCardProps {
    task: Task
    onAssignToWorkflow?: (taskId: string, workflowId: string) => void
    onClick?: (taskId: string) => void
    draggable?: boolean
    workflows?: TaskWorkflow[]
}

export function TaskCard({
    task,
    onAssignToWorkflow,
    onClick,
    draggable = false,
    workflows = [],
}: TaskCardProps): JSX.Element {
    const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>('')

    // Determine if task is in backlog (no workflow assigned)
    const isInBacklog = !task.workflow || !task.current_stage

    const handleCardClick = (): void => {
        if (onClick) {
            onClick(task.id)
        }
    }

    const handleAssignToWorkflow = (e: React.MouseEvent): void => {
        e.stopPropagation()
        if (selectedWorkflowId && onAssignToWorkflow) {
            onAssignToWorkflow(task.id, selectedWorkflowId)
        }
    }

    return (
        <LemonCard
            className={`p-3 ${draggable ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'}`}
            hoverEffect={true}
            onClick={handleCardClick}
        >
            <div className="flex justify-between items-start mb-2">
                <h4 className="font-medium text-sm leading-tight">{task.title}</h4>
            </div>

            <p className="text-xs text-muted mb-3 line-clamp-2">{task.description}</p>

            {/* GitHub Integration Status */}
            {(task.github_branch || task.github_pr_url) && (
                <div className="flex items-center gap-1 mb-2">
                    <IconGithub className="text-xs" />
                    {task.github_branch && (
                        <div className="flex items-center gap-1 text-xs text-muted">
                            <IconBranch />
                            <span className="truncate max-w-32">{task.github_branch}</span>
                        </div>
                    )}
                    {task.github_pr_url && (
                        <Link
                            to={task.github_pr_url}
                            target="_blank"
                            className="flex items-center gap-1 text-xs text-link hover:text-link-hover"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <span>↗</span>
                            <span>PR</span>
                        </Link>
                    )}
                </div>
            )}

            {/* Repository Information */}
            {task.repository_scope && (
                <div className="mb-2">
                    <div className="flex items-center gap-2 text-xs text-muted">
                        <span className="font-medium">Repos:</span>
                        {task.repository_scope === 'single' && task.primary_repository && (
                            <span className="text-primary">
                                {task.primary_repository.organization}/{task.primary_repository.repository}
                            </span>
                        )}
                        {task.repository_scope === 'multiple' && task.repository_list && (
                            <span className="text-primary">{task.repository_list.length} repositories</span>
                        )}
                        {task.repository_scope === 'smart_select' && <span className="text-primary">Smart Select</span>}
                    </div>
                </div>
            )}

            <div className="flex justify-between items-center">
                <span
                    className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                        ORIGIN_PRODUCT_COLORS[task.origin_product]
                    }`}
                >
                    {ORIGIN_PRODUCT_LABELS[task.origin_product]}
                </span>

                {isInBacklog && onAssignToWorkflow && workflows.length > 0 && (
                    <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                        <LemonSelect
                            value={selectedWorkflowId}
                            onChange={(value) => setSelectedWorkflowId(value)}
                            options={[
                                { value: '', label: 'Select workflow...' },
                                ...workflows.map((workflow) => ({
                                    value: workflow.id,
                                    label: workflow.name,
                                })),
                            ]}
                            placeholder="Select workflow"
                            size="small"
                            className="min-w-32"
                        />
                        <LemonButton
                            size="xsmall"
                            type="primary"
                            onClick={handleAssignToWorkflow}
                            disabled={!selectedWorkflowId}
                        >
                            Assign
                        </LemonButton>
                    </div>
                )}
            </div>
        </LemonCard>
    )
}
