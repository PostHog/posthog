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

    const selectedTaskId = taskId && taskId !== 'new' ? taskId : null

    const rightPane = selectedTaskId ? <TaskDetailPage taskId={selectedTaskId} isMobile={false} /> : <TaskComposer />

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
        // List view scrolls with the page (main), not an inner container, so no fixed height here.
        return (
            <SceneContent>
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
