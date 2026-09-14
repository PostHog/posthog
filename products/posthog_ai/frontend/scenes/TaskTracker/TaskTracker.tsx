import { useValues } from 'kea'

import { AllowTrainingCallout } from 'lib/components/AllowTrainingCallout/AllowTrainingCallout'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/queries/schema/schema-general'

import { TaskComposer } from './components/TaskComposer'
import { TaskCreateThread } from './components/TaskCreateThread'
import { TaskDetailPage } from './components/TaskDetailPage'
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

    if (selectedTaskId || activeCreation) {
        return (
            <div className="flex flex-col h-full min-h-0">
                <AllowTrainingCallout featureName={selectedTaskId ? 'PostHog Desktop' : 'Tasks'} />
                <div className="flex flex-1 min-h-0 flex-col overflow-hidden">
                    {selectedTaskId ? (
                        <TaskDetailPage taskId={selectedTaskId} isMobile={isMobile} />
                    ) : (
                        <TaskCreateThread streamKey={activeCreation!.streamKey} isMobile={isMobile} />
                    )}
                </div>
            </div>
        )
    }

    return (
        <SceneContent className="h-full">
            <AllowTrainingCallout featureName="Tasks" />
            <div className="flex flex-1 min-h-0 flex-col overflow-hidden">
                <TaskComposer />
            </div>
        </SceneContent>
    )
}
