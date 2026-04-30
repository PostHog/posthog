import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlus } from '@posthog/icons'
import {
    LemonBadge,
    LemonButton,
    LemonInput,
    LemonSelect,
    type LemonSelectOption,
    LemonSwitch,
    LemonTag,
    ProfilePicture,
    Spinner,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TASK_STATUS_CONFIG } from '../lib/task-status'
import { tasksLogic } from '../logics/tasksLogic'
import { taskTrackerSceneLogic } from '../logics/taskTrackerSceneLogic'
import { Task, TaskRunStatus } from '../types'
import { TaskCreateModal } from './TaskCreateModal'
import { TaskStatusBadge } from './TaskStatusBadge'
import { UserFilter } from './UserFilter'

export function TasksList(): JSX.Element {
    const { searchQuery, repository, status, showInternal, isDev, isCreateModalOpen } = useValues(taskTrackerSceneLogic)
    const { tasks, tasksLoading, repositories } = useValues(tasksLogic)
    const { setSearchQuery, setRepository, setStatus, setShowInternal, openCreateModal, closeCreateModal } =
        useActions(taskTrackerSceneLogic)
    const columns: LemonTableColumn<Task, keyof Task | undefined>[] = [
        {
            title: 'Task',
            key: 'title',
            width: '40%',
            render: (_: any, task: Task) => (
                <div className="flex flex-col gap-1 min-w-0">
                    <div className="flex items-center gap-2 min-w-0">
                        <Link
                            to={urls.taskDetail(task.id)}
                            className="font-semibold text-link shrink-0"
                            onClick={(e) => e.stopPropagation()}
                        >
                            {task.slug}
                        </Link>
                        <span className="text-default truncate">{task.title}</span>
                        {task.internal && (
                            <LemonTag type="warning" size="small">
                                Internal
                            </LemonTag>
                        )}
                    </div>
                    {task.description && <div className="text-muted text-xs line-clamp-1">{task.description}</div>}
                </div>
            ),
        },
        {
            title: 'Repository',
            key: 'repository',
            width: '20%',
            render: (_: any, task: Task) => <span className="text-sm">{task.repository}</span>,
        },
        {
            title: 'Status',
            key: 'latest_run',
            width: '15%',
            render: (_: any, task: Task) => <TaskStatusBadge task={task} />,
        },
        {
            title: 'Created by',
            key: 'created_by',
            width: '15%',
            render: (_: any, task: Task) => {
                if (!task.created_by) {
                    return <span className="text-sm text-muted">-</span>
                }
                return (
                    <div className="flex items-center gap-2">
                        <ProfilePicture user={task.created_by} size="sm" />
                        <span className="text-sm truncate">{task.created_by.first_name || task.created_by.email}</span>
                    </div>
                )
            },
        },
        {
            title: 'Created',
            key: 'created_at',
            width: '10%',
            render: (_: any, task: Task) => <TZLabel time={task.created_at} showSeconds className="text-sm" />,
        },
    ]

    const statusOptions: LemonSelectOption<TaskRunStatus | 'all'>[] = [
        'all',
        TaskRunStatus.NOT_STARTED,
        TaskRunStatus.QUEUED,
        TaskRunStatus.IN_PROGRESS,
        TaskRunStatus.COMPLETED,
        TaskRunStatus.FAILED,
        TaskRunStatus.CANCELLED,
    ].map((key) => {
        const config = TASK_STATUS_CONFIG[key as TaskRunStatus | 'all']
        return {
            value: key as TaskRunStatus | 'all',
            label: (
                <div className="flex items-center gap-2">
                    <LemonBadge status={config.status} size="small" />
                    <span>{config.label}</span>
                </div>
            ),
        }
    })

    return (
        <div>
            <div className="flex items-center justify-between mb-4 gap-2">
                <div className="flex items-center gap-2 flex-1">
                    <LemonInput
                        type="search"
                        placeholder="Search tasks..."
                        value={searchQuery}
                        onChange={setSearchQuery}
                        className="flex-1 max-w-sm"
                    />
                    {repositories.length > 0 && (
                        <LemonSelect
                            value={repository}
                            onChange={setRepository}
                            options={[
                                { label: 'All repositories', value: 'all' },
                                ...repositories.map((repo) => ({ label: repo, value: repo })),
                            ]}
                            className="min-w-48"
                        />
                    )}
                    <LemonSelect value={status} onChange={setStatus} options={statusOptions} className="min-w-32" />
                    <UserFilter />
                    {isDev && (
                        <LemonSwitch
                            label="Show internal"
                            checked={showInternal}
                            onChange={setShowInternal}
                            bordered
                            size="small"
                        />
                    )}
                </div>
                <LemonButton type="primary" icon={<IconPlus />} onClick={openCreateModal}>
                    New task
                </LemonButton>
            </div>

            {tasksLoading ? (
                <div className="flex items-center justify-center h-64">
                    <Spinner />
                </div>
            ) : (
                <LemonTable
                    dataSource={tasks}
                    columns={columns}
                    rowKey="id"
                    onRow={(task) => ({
                        onClick: (e) => {
                            const url = urls.taskDetail(task.id)
                            if (e.metaKey || e.ctrlKey || e.button === 1) {
                                window.open(url, '_blank')
                            } else {
                                router.actions.push(url)
                            }
                        },
                        className: 'cursor-pointer hover:bg-bg-light',
                    })}
                    emptyState={
                        <div className="text-center py-8">
                            <p className="text-muted mb-2">No tasks found</p>
                        </div>
                    }
                />
            )}

            <TaskCreateModal isOpen={isCreateModalOpen} onClose={closeCreateModal} />
        </div>
    )
}
