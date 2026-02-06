import { useActions, useValues } from 'kea'

import { IconBug } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { preflightLogicType } from 'scenes/PreflightCheck/preflightLogicType'
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
    const { isDev } = useValues<preflightLogicType>(preflightLogic)
    const { devOnlyIsRunningClustering } = useValues(taskTrackerSceneLogic)
    const { devOnlyInferTasks } = useActions(taskTrackerSceneLogic)

    if (!isEnabled) {
        return <NotFound object="Tasks" caption="This feature is not enabled for your project." />
    }

    const debugActions = isDev ? (
        <Tooltip title="Run video segment clustering workflow for this team (DEBUG only)">
            <LemonButton
                icon={<IconBug />}
                size="small"
                type="secondary"
                onClick={() => devOnlyInferTasks()}
                loading={devOnlyIsRunningClustering}
                data-attr="run-task-clustering-button"
            >
                Run task clusterization on last 7 days
            </LemonButton>
        </Tooltip>
    ) : undefined

    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfigurations[Scene.TaskTracker].name}
                description={sceneConfigurations[Scene.TaskTracker].description}
                resourceType={{
                    type: sceneConfigurations[Scene.TaskTracker].iconType || 'default_icon_type',
                }}
                actions={debugActions}
            />

            <TasksList />
        </SceneContent>
    )
}
