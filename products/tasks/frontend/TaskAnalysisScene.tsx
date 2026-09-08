import { useValues } from 'kea'

import { IconStethoscope } from '@posthog/icons'
import { LemonBanner, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { TaskAnalysisRunsTable } from './components/TaskAnalysisRunsTable'
import { TaskAnalysisSettings } from './components/TaskAnalysisSettings'
import { type TaskAnalysisTab, taskAnalysisSceneLogic } from './logics/taskAnalysisSceneLogic'

export const scene: SceneExport = {
    component: TaskAnalysisScene,
    logic: taskAnalysisSceneLogic,
}

const TAB_DESCRIPTIONS: Record<TaskAnalysisTab, string> = {
    runs: 'The analysis runs of this project, newest first. Open a row for the activities the run reported.',
    settings: 'The model that analysis runs use in this project.',
}

export function TaskAnalysisScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab } = useValues(taskAnalysisSceneLogic)

    if (!featureFlags[FEATURE_FLAGS.POSTHOG_CODE_TASK_ANALYSIS]) {
        return (
            <SceneContent>
                <SceneTitleSection
                    name="Task analysis"
                    resourceType={{ type: 'task', forceIcon: <IconStethoscope /> }}
                />
                <LemonBanner type="info">Task analysis is not enabled for this project.</LemonBanner>
            </SceneContent>
        )
    }

    const tabs: LemonTab<TaskAnalysisTab>[] = [
        {
            key: 'runs',
            label: 'Runs',
            content: <TaskAnalysisRunsTable />,
            link: urls.taskAnalysisRuns(),
            'data-attr': 'task-analysis-runs-tab',
        },
        {
            key: 'settings',
            label: 'Settings',
            content: <TaskAnalysisSettings />,
            link: urls.taskAnalysisSettings(),
            'data-attr': 'task-analysis-settings-tab',
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="Task analysis"
                description={TAB_DESCRIPTIONS[activeTab]}
                resourceType={{ type: 'task', forceIcon: <IconStethoscope /> }}
            />
            <LemonTabs activeKey={activeTab} data-attr="task-analysis-tabs" tabs={tabs} sceneInset />
        </SceneContent>
    )
}
