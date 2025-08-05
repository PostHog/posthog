import { LemonButton, LemonCard } from '@posthog/lemon-ui'
import { IconGithub, IconBranch } from 'lib/lemon-ui/icons'
import { Task, TaskStatus } from '../types'
import { ORIGIN_PRODUCT_LABELS, ORIGIN_PRODUCT_COLORS } from '../constants'

interface TaskCardProps {
    task: Task
    onScope?: (taskId: string) => void
    onClick?: (taskId: string) => void
    draggable?: boolean
}

export function TaskCard({ task, onScope, onClick, draggable = false }: TaskCardProps): JSX.Element {
    const handleCardClick = (): void => {
        if (onClick) {
            onClick(task.id)
        }
    }

    return (
        <LemonCard
            className={`p-3 ${draggable ? 'cursor-move' : 'cursor-pointer'}`}
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
                        <a
                            href={task.github_pr_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-1 text-xs text-link hover:text-link-hover"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <span>↗</span>
                            <span>PR</span>
                        </a>
                    )}
                </div>
            )}

            {/* Repository Information */}
            {task.repository_scope && (
                <div className="mb-2">
                    <div className="flex items-center gap-2 text-xs text-muted">
                        <span className="font-medium">Repos:</span>
                        {task.repository_scope === 'single' && task.primary_repository && (
                            <span className="text-primary">{task.primary_repository.organization}/{task.primary_repository.repository}</span>
                        )}
                        {task.repository_scope === 'multiple' && task.repository_list && (
                            <span className="text-primary">{task.repository_list.length} repositories</span>
                        )}
                        {task.repository_scope === 'smart_select' && (
                            <span className="text-primary">Smart Select</span>
                        )}
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

                {task.status === TaskStatus.BACKLOG && onScope && (
                    <LemonButton
                        size="xsmall"
                        type="primary"
                        onClick={(e) => {
                            e.stopPropagation()
                            onScope(task.id)
                        }}
                    >
                        Scope
                    </LemonButton>
                )}
            </div>
        </LemonCard>
    )
}
