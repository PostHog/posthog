import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { IconExclamation } from 'lib/lemon-ui/icons'
import { IconInfo, IconExternal, IconClock, IconCheckCircle } from '@posthog/icons'

import { Task } from '../types'
import { tasksLogic } from '../tasksLogic'

export function TaskControlPanel(): JSX.Element {
    const { tasks, workflowStages, allWorkflows } = useValues(tasksLogic)
    const { openTaskModal } = useActions(tasksLogic)

    // Helper to get stage key for a task
    const getTaskStageKey = (task: Task): string => {
        if (task.workflow && task.current_stage) {
            const stage = allWorkflows
                .flatMap(w => w.stages || [])
                .find(s => s.id === task.current_stage)
            return stage?.key || 'backlog'
        }
        return 'backlog'
    }

    const tasksByStage = workflowStages.reduce((acc, stage) => {
        acc[stage.key] = tasks.filter(task => getTaskStageKey(task) === stage.key)
        return acc
    }, {} as Record<string, Task[]>)

    const needsAttention = tasks.filter(task => {
        const stageKey = getTaskStageKey(task)
        return stageKey === 'testing' || stageKey === 'done'
    })

    const activeTasks = tasks.filter(task => {
        const stageKey = getTaskStageKey(task)
        return stageKey === 'todo' || stageKey === 'in_progress'
    })

    const recentlyCompleted = tasks
        .filter(task => getTaskStageKey(task) === 'done')
        .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
        .slice(0, 5)

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center">
                <div>
                    <h2 className="text-xl font-semibold">Task Control Panel</h2>
                    <p className="text-muted text-sm mt-1">
                        Monitor and manage your task workflows
                    </p>
                </div>
            </div>

            {/* Overview Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <OverviewCard
                    title="Total Tasks"
                    value={tasks.length}
                    icon={<IconInfo className="w-5 h-5" />}
                    color="text-primary"
                />
                <OverviewCard
                    title="Active Tasks"
                    value={activeTasks.length}
                    icon={<IconClock className="w-5 h-5" />}
                    color="text-warning"
                />
                <OverviewCard
                    title="Need Attention"
                    value={needsAttention.length}
                    icon={<IconExclamation className="w-5 h-5" />}
                    color="text-danger"
                />
                <OverviewCard
                    title="Completed"
                    value={recentlyCompleted.length}
                    icon={<IconCheckCircle className="w-5 h-5" />}
                    color="text-success"
                />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Tasks Needing Attention */}
                <LemonCard className="p-6">
                    <div className="flex justify-between items-center mb-4">
                        <h3 className="text-lg font-medium">Tasks Needing Attention</h3>
                        <LemonTag type="warning">{needsAttention.length}</LemonTag>
                    </div>
                    
                    <div className="space-y-3">
                        {needsAttention.length === 0 ? (
                            <p className="text-muted text-sm">No tasks need attention</p>
                        ) : (
                            needsAttention.slice(0, 5).map((task) => (
                                <TaskSummaryCard 
                                    key={task.id}
                                    task={task}
                                    onClick={() => openTaskModal(task.id)}
                                />
                            ))
                        )}
                    </div>
                </LemonCard>

                {/* Recently Completed */}
                <LemonCard className="p-6">
                    <div className="flex justify-between items-center mb-4">
                        <h3 className="text-lg font-medium">Recently Completed</h3>
                        <LemonTag type="success">{recentlyCompleted.length}</LemonTag>
                    </div>
                    
                    <div className="space-y-3">
                        {recentlyCompleted.length === 0 ? (
                            <p className="text-muted text-sm">No completed tasks</p>
                        ) : (
                            recentlyCompleted.map((task) => (
                                <TaskSummaryCard 
                                    key={task.id}
                                    task={task}
                                    onClick={() => openTaskModal(task.id)}
                                />
                            ))
                        )}
                    </div>
                </LemonCard>
            </div>

            {/* Workflow Stage Overview */}
            <LemonCard className="p-6">
                <h3 className="text-lg font-medium mb-4">Workflow Overview</h3>
                
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
                    {workflowStages.map((stage) => {
                        const stageTasks = tasksByStage[stage.key] || []
                        return (
                            <div
                                key={stage.id}
                                className="p-4 bg-bg-light rounded-lg"
                            >
                                <div className="flex items-center gap-2 mb-2">
                                    <div
                                        className="w-3 h-3 rounded-full"
                                        style={{ backgroundColor: stage.color }}
                                    />
                                    <h4 className="font-medium text-sm">{stage.name}</h4>
                                </div>
                                
                                <div className="text-2xl font-bold text-primary mb-1">
                                    {stageTasks.length}
                                </div>
                                
                                <div className="text-xs text-muted">
                                    {stage.is_manual_only ? 'Manual' : 'Automated'}
                                </div>
                                
                                {stageTasks.length > 0 && (
                                    <div className="mt-3">
                                        <div className="text-xs text-muted mb-1">Latest:</div>
                                        <div className="text-xs font-medium truncate">
                                            {stageTasks[stageTasks.length - 1]?.title}
                                        </div>
                                    </div>
                                )}
                            </div>
                        )
                    })}
                </div>
            </LemonCard>
        </div>
    )
}

interface OverviewCardProps {
    title: string
    value: number
    icon: React.ReactNode
    color: string
}

function OverviewCard({ title, value, icon, color }: OverviewCardProps): JSX.Element {
    return (
        <LemonCard className="p-4">
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-sm text-muted">{title}</p>
                    <p className="text-2xl font-bold">{value}</p>
                </div>
                <div className={color}>
                    {icon}
                </div>
            </div>
        </LemonCard>
    )
}

interface TaskSummaryCardProps {
    task: Task
    onClick: () => void
}

function TaskSummaryCard({ task, onClick }: TaskSummaryCardProps): JSX.Element {
    const { allWorkflows } = useValues(tasksLogic)
    
    const getTaskStageKey = (task: Task): string => {
        if (task.workflow && task.current_stage) {
            const stage = allWorkflows
                .flatMap(w => w.stages || [])
                .find(s => s.id === task.current_stage)
            return stage?.key || 'backlog'
        }
        return 'backlog'
    }

    const getStageColor = (stageKey: string): string => {
        switch (stageKey) {
            case 'todo':
                return 'text-primary'
            case 'in_progress':
                return 'text-warning'
            case 'testing':
                return 'text-purple'
            case 'done':
                return 'text-success'
            default:
                return 'text-muted'
        }
    }

    return (
        <div
            className="flex items-center justify-between p-3 bg-bg-light rounded hover:bg-bg-3000 cursor-pointer transition-colors"
            onClick={onClick}
        >
            <div className="flex-1">
                <div className="font-medium text-sm mb-1 truncate">
                    {task.title}
                </div>
                <div className="flex items-center gap-2">
                    <LemonTag size="small" className={getStageColor(getTaskStageKey(task))}>
                        {getTaskStageKey(task)}
                    </LemonTag>
                    {task.github_pr_url && (
                        <LemonTag size="small" type="highlight">
                            PR Ready
                        </LemonTag>
                    )}
                </div>
            </div>
            <LemonButton
                size="xsmall"
                type="secondary"
                icon={<IconExternal />}
                onClick={(e) => {
                    e.stopPropagation()
                    onClick()
                }}
            />
        </div>
    )
}