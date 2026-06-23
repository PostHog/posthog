import { AllowTrainingCallout } from 'lib/components/AllowTrainingCallout/AllowTrainingCallout'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { TaskDetailPage } from './components/TaskDetailPage'
import { TaskDetailSceneLogicProps, taskDetailSceneLogic } from './logics/taskDetailSceneLogic'

export const scene: SceneExport<TaskDetailSceneLogicProps> = {
    component: TaskDetailScene,
    logic: taskDetailSceneLogic,
    productKey: ProductKey.TASKS,
    paramsToProps: ({ params: { taskId } }) => ({
        taskId: taskId,
    }),
}

export function TaskDetailScene({ taskId }: TaskDetailSceneLogicProps): JSX.Element {
    return (
        <>
            <AllowTrainingCallout featureName="PostHog Code" />
            <TaskDetailPage taskId={taskId} />
        </>
    )
}
