import { type ReactNode } from 'react'

import { IconArchive } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import {
    ScenePanel,
    ScenePanelActionsSection,
    ScenePanelDivider,
    ScenePanelInfoSection,
} from '~/layout/scenes/SceneLayout'

import type { TaskRunDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import type { Task } from '../../../types/taskTypes'
import { TaskDebugLogsPanelToggle } from './TaskDebugLogsPanelToggle'
import { TaskPanelSkeleton, TaskRunMetadataSkeleton } from './taskDetailSkeletons'
import { TaskErrorBanner } from './TaskErrorBanner'
import { TaskRunMetadata } from './TaskRunMetadata'

export interface TaskRunSceneShellProps {
    /** The loaded task, or `null` while loading (or during an optimistic create, before it exists). */
    task: Task | null
    /** The run whose metadata heads the thread, or `null` while loading. */
    selectedRun: TaskRunDetailDTOApi | null
    /** Drives the title/panel/metadata skeletons — the single unified loading affordance for the header. */
    isHeaderLoading?: boolean
    /** Title-bar action buttons (or their skeleton). Supplied by the caller so the shell stays presentational. */
    titleActions?: JSX.Element
    onArchive: () => void
    taskError: string | null
    onRetry: () => void
    isMobile: boolean
    /** The run-log slot (the streamed thread). */
    children: ReactNode
}

/**
 * The task-run scene chrome — scene panel, title header, run metadata, divider — around a run-log slot.
 * Purely presentational: both the detail page (wired from `taskDetailSceneLogic`) and the optimistic
 * create thread render it, so the thread keeps the same layout across the `/tasks/new → /tasks/:id` handoff.
 */
export function TaskRunSceneShell({
    task,
    selectedRun,
    isHeaderLoading = false,
    titleActions,
    onArchive,
    taskError,
    onRetry,
    isMobile,
    children,
}: TaskRunSceneShellProps): JSX.Element {
    return (
        <SceneContent className="h-full min-h-0 gap-y-0">
            <ScenePanel>
                {isHeaderLoading ? (
                    <TaskPanelSkeleton />
                ) : task ? (
                    <>
                        <ScenePanelInfoSection>
                            <div className="flex flex-col gap-3">
                                <div>
                                    <div className="text-xs text-muted mb-1">Task ID</div>
                                    <div className="font-mono text-sm">{task.slug}</div>
                                </div>
                                <div>
                                    <div className="text-xs text-muted mb-1">Repository</div>
                                    <div className="text-sm">{task.repository}</div>
                                </div>
                                <div>
                                    <div className="text-xs text-muted mb-1">Created by</div>
                                    <div className="text-sm">
                                        {task.created_by?.first_name || task.created_by?.email || 'Unknown'}
                                    </div>
                                </div>
                                <div>
                                    <div className="text-xs text-muted mb-1">Created</div>
                                    <div className="text-sm">{dayjs(task.created_at).format('MMM D, YYYY HH:mm')}</div>
                                </div>
                            </div>
                        </ScenePanelInfoSection>

                        <ScenePanelDivider />

                        <TaskDebugLogsPanelToggle />

                        <ScenePanelActionsSection>
                            <ButtonPrimitive menuItem variant="danger" onClick={onArchive}>
                                <IconArchive />
                                Archive task
                            </ButtonPrimitive>
                        </ScenePanelActionsSection>
                    </>
                ) : null}
            </ScenePanel>

            {taskError && !task ? (
                <TaskErrorBanner
                    title="We couldn't load this task."
                    message={taskError}
                    onRetry={onRetry}
                    dataAttr="task-load-error"
                    className="max-w-200"
                />
            ) : (
                <>
                    {taskError && (
                        <TaskErrorBanner
                            title="We couldn't load this task."
                            message={taskError}
                            onRetry={onRetry}
                            dataAttr="task-load-error"
                            className="max-w-200"
                        />
                    )}

                    <header className={cn('flex flex-col gap-y-2', taskError && 'mt-4')}>
                        <SceneTitleSection
                            className="-mt-2"
                            name={task?.title || 'Task'}
                            description={null}
                            resourceType={{ type: 'task' }}
                            isLoading={isHeaderLoading}
                            canEdit={false}
                            forceBackTo={
                                isMobile
                                    ? {
                                          key: 'posthog-ai',
                                          name: 'PostHog AI',
                                          path: urls.ai(),
                                      }
                                    : undefined
                            }
                            actions={titleActions}
                        />

                        {isHeaderLoading ? (
                            <TaskRunMetadataSkeleton />
                        ) : (
                            selectedRun && <TaskRunMetadata selectedRun={selectedRun} />
                        )}

                        <LemonDivider className="hidden lg:block mb-0 mt-2" />
                    </header>

                    {children}
                </>
            )}
        </SceneContent>
    )
}
