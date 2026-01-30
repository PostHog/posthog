import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { TasksList } from './components/TasksList'
import { taskTrackerSceneLogic } from './logics/taskTrackerSceneLogic'

export const scene: SceneExport = {
    component: TaskTracker,
    logic: taskTrackerSceneLogic,
    productKey: ProductKey.TASKS,
}

export function TaskTracker(): JSX.Element {
    const isEnabled = useFeatureFlag('TASKS')
    useValues(taskTrackerSceneLogic) // Mount the logic

    if (!isEnabled) {
        return <NotFound object="Tasks" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.TaskTracker].name}
                description={sceneConfigurations[Scene.TaskTracker].description}
                resourceType={{
                    type: sceneConfigurations[Scene.TaskTracker].iconType || 'default_icon_type',
                }}
            />

            <TasksList />
        </SceneContent>
    )
}
