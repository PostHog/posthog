import { AllowTrainingCallout } from 'lib/components/AllowTrainingCallout/AllowTrainingCallout'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { TaskComposer } from './components/TaskComposer'
import { TaskDetailPage } from './components/TaskDetailPage'
import { TasksListColumn } from './components/TasksListColumn'
import { taskTrackerSceneLogic } from './logics/taskTrackerSceneLogic'

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

    const rightPane = selectedTaskId ? <TaskDetailPage taskId={selectedTaskId} /> : <TaskComposer />

    if (isMobile) {
        // Single column: detail, composer, or the list (with a "Create a new task" row).
        if (selectedTaskId) {
            return (
                <>
                    <AllowTrainingCallout featureName="PostHog Code" />
                    <TaskDetailPage taskId={selectedTaskId} />
                </>
            )
        }
        if (taskId === 'new') {
            return (
                <SceneContent>
                    <AllowTrainingCallout featureName="Tasks" />
                    <TaskComposer />
                </SceneContent>
            )
        }
        return (
            <SceneContent>
                <SceneTitleSection
                    name={sceneConfigurations[Scene.TaskTracker].name}
                    description={sceneConfigurations[Scene.TaskTracker].description}
                    resourceType={{ type: sceneConfigurations[Scene.TaskTracker].iconType || 'default_icon_type' }}
                />
                <AllowTrainingCallout featureName="Tasks" />
                <div className="flex flex-col min-h-[60vh]">
                    <TasksListColumn selectedTaskId={null} isMobile />
                </div>
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <AllowTrainingCallout featureName="Tasks" />
            <div className="flex flex-1 min-h-[70vh] gap-4">
                <div className="w-80 shrink-0 border-r border-primary">
                    <TasksListColumn selectedTaskId={selectedTaskId} />
                </div>
                <div className="flex-1 min-w-0 overflow-auto">{rightPane}</div>
            </div>
        </SceneContent>
    )
}
