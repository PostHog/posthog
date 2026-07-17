import { useValues } from 'kea'

import { AllowTrainingCallout } from 'lib/components/AllowTrainingCallout/AllowTrainingCallout'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { TaskComposer } from './components/TaskComposer'
import { TaskCreateThread } from './components/TaskCreateThread'
import { TaskDetailPage } from './components/TaskDetailPage'
import { TasksListColumn } from './components/TasksListColumn'
import { taskTrackerSceneLogic } from './taskTrackerSceneLogic'

export interface TaskTrackerProps {
    /** From the `/tasks/:taskId` route. A UUID selects a task; `new` or absent shows the composer. */
    taskId?: string
}

export const scene: SceneExport<TaskTrackerProps> = {
    component: TaskTracker,
    logic: taskTrackerSceneLogic,
    productKey: ProductKey.TASKS,
    paramsToProps: ({ params: { taskId } }) => ({ taskId }),
}

export function TaskTracker({ taskId }: TaskTrackerProps): JSX.Element {
    const { isWindowLessThan } = useWindowSize()
    const isMobile = isWindowLessThan('lg')
    const { activeCreation } = useValues(taskTrackerSceneLogic)

    const selectedTaskId = taskId && taskId !== 'new' ? taskId : null

    // While an optimistic create is in flight (and no task is selected), the thread opens immediately in place
    // of the composer — see `taskTrackerSceneLogic.submit`.
    const composerPane = activeCreation ? (
        <TaskCreateThread streamKey={activeCreation.streamKey} isMobile={isMobile} />
    ) : (
        <TaskComposer />
    )
    const rightPane = selectedTaskId ? <TaskDetailPage taskId={selectedTaskId} isMobile={false} /> : composerPane

    if (isMobile) {
        // Single column: detail, composer, or the list (with a "Create a new task" row).
        if (selectedTaskId) {
            return (
                <div className="flex flex-col h-full min-h-0">
                    <AllowTrainingCallout featureName="PostHog Code" />
                    <div className="flex flex-1 min-h-0 flex-col overflow-hidden">
                        <TaskDetailPage taskId={selectedTaskId} isMobile />
                    </div>
                </div>
            )
        }
        if (taskId === 'new') {
            // Optimistic create renders the same scene shell as the detail page (which carries its own
            // SceneContent + back button), so wrap it like the detail branch — not the composer's
            // SceneContent — to keep the create → detail handoff seamless and avoid nesting SceneContent.
            if (activeCreation) {
                return (
                    <div className="flex flex-col h-full min-h-0">
                        <AllowTrainingCallout featureName="Tasks" />
                        <div className="flex flex-1 min-h-0 flex-col overflow-hidden">
                            <TaskCreateThread streamKey={activeCreation.streamKey} isMobile />
                        </div>
                    </div>
                )
            }
            return (
                <SceneContent className="h-full">
                    <SceneBreadcrumbBackButton
                        forceBackTo={{
                            key: 'tasks',
                            name: 'Tasks',
                            path: urls.taskTracker(),
                        }}
                        className="mt-10 w-fit"
                    />
                    <AllowTrainingCallout featureName="Tasks" />
                    <div className="flex flex-1 min-h-0 flex-col overflow-hidden">
                        <TaskComposer />
                    </div>
                </SceneContent>
            )
        }
        // Full-height column so the virtualized list has a bounded height to fill; the header stays
        // fixed and the list owns its own scroll (the page no longer scrolls).
        return (
            <SceneContent className="h-full">
                <SceneTitleSection
                    name={sceneConfigurations[Scene.TaskTracker].name}
                    description={sceneConfigurations[Scene.TaskTracker].description}
                    resourceType={{ type: sceneConfigurations[Scene.TaskTracker].iconType || 'default_icon_type' }}
                />
                <AllowTrainingCallout featureName="Tasks" />
                <TasksListColumn selectedTaskId={null} isMobile />
            </SceneContent>
        )
    }

    return (
        <SceneContent className="h-full">
            <AllowTrainingCallout featureName="Tasks" />
            <div className="flex flex-1 min-h-0 gap-4">
                <div className="w-72 shrink-0 pl-0 flex flex-col min-h-0 border-r border-primary">
                    <TasksListColumn selectedTaskId={selectedTaskId} />
                </div>
                <div className="flex-1 min-w-0 flex flex-col min-h-0">{rightPane}</div>
            </div>
        </SceneContent>
    )
}
