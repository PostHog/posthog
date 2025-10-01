import { useActions, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { BacklogView } from './components/BacklogView'
import { GitHubIntegrationSettings } from './components/GitHubIntegrationSettings'
import { KanbanView } from './components/KanbanView'
import { TaskControlPanel } from './components/TaskControlPanel'
import { tasksLogic } from './tasksLogic'
import type { TaskTrackerTab } from './types'

export const scene: SceneExport = {
    component: TaskTracker,
    logic: tasksLogic,
}

export function TaskTracker(): JSX.Element {
    const { activeTab } = useValues(tasksLogic)
    const { setActiveTab } = useActions(tasksLogic)
    const isEnabled = useFeatureFlag('TASKS')

    if (!isEnabled) {
        return <NotFound object="Tasks" caption="This feature is not enabled for your project." />
    }

    const tabs: { key: TaskTrackerTab; label: string; content: React.ReactNode }[] = [
        {
            key: 'dashboard' as const,
            label: 'Dashboard',
            content: <TaskControlPanel />,
        },
        {
            key: 'backlog' as const,
            label: 'All Tasks',
            content: <BacklogView />,
        },
        {
            key: 'kanban' as const,
            label: 'Workflows',
            content: <KanbanView />,
        },
        {
            key: 'settings' as const,
            label: 'Settings',
            content: <GitHubIntegrationSettings />,
        },
    ]

    return (
        <div className="TaskTracker">
            <div className="space-y-4">
                <SceneTitleSection
                    name="Tasks"
                    resourceType={{
                        type: 'task',
                    }}
                />
                <SceneDivider />

                <LemonTabs activeKey={activeTab} onChange={setActiveTab} tabs={tabs} size="medium" sceneInset />
            </div>
        </div>
    )
}
