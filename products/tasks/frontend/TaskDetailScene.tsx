import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
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
    const isEnabled = useFeatureFlag('TASKS')

    if (!isEnabled) {
        return <NotFound object="Tasks" caption="This feature is not enabled for your project." />
    }

    return <TaskDetailPage taskId={taskId} />
}
