import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { TaskDetailPage } from './components/TaskDetailPage'
import { TaskDetailLogicProps, taskDetailLogic } from './taskDetailLogic'

export const scene: SceneExport<TaskDetailLogicProps> = {
    component: TaskDetailScene,
    logic: taskDetailLogic,
    paramsToProps: ({ params: { taskId } }) => ({
        taskId: taskId,
    }),
}

export function TaskDetailScene(): JSX.Element {
    const { task, taskLoading } = useValues(taskDetailLogic)
    const isEnabled = useFeatureFlag('TASKS')

    if (!isEnabled) {
        return <NotFound object="Tasks" caption="This feature is not enabled for your project." />
    }

    if (taskLoading) {
        return <div>Loading...</div>
    }

    if (!task) {
        return <NotFound object="Task" />
    }

    return <TaskDetailPage task={task} />
}
