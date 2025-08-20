import { useActions, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { BacklogView } from './components/BacklogView'
import { GitHubIntegrationSettings } from './components/GitHubIntegrationSettings'
import { KanbanView } from './components/KanbanView'
import { tasksLogic } from './tasksLogic'

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

    const tabs = [
        {
            key: 'backlog' as const,
            label: 'Backlog',
            content: <BacklogView />,
        },
        {
            key: 'kanban' as const,
            label: 'Kanban Board',
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
                <div>
                    <h1 className="text-2xl font-bold">Tasks</h1>
                    <p className="text-muted">Manage and track development tasks across all PostHog products</p>
                </div>

                <LemonTabs activeKey={activeTab} onChange={setActiveTab} tabs={tabs} size="medium" />
            </div>
        </div>
    )
}
