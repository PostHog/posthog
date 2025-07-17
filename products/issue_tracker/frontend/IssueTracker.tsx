import { useValues, useActions } from 'kea'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { issueTrackerLogic } from './IssueTrackerLogic'
import { BacklogView } from './components/BacklogView'
import { KanbanView } from './components/KanbanView'

export const scene: SceneExport = {
    component: IssueTracker,
    logic: issueTrackerLogic,
}

export function IssueTracker(): JSX.Element {
    const { activeTab } = useValues(issueTrackerLogic)
    const { setActiveTab } = useActions(issueTrackerLogic)

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
    ]

    return (
        <div className="IssueTracker">
            <div className="space-y-4">
                <div>
                    <h1 className="text-2xl font-bold">Issue Tracker</h1>
                    <p className="text-muted">Manage and track development issues across all PostHog products</p>
                </div>

                <LemonTabs activeKey={activeTab} onChange={setActiveTab} tabs={tabs} size="medium" />
            </div>
        </div>
    )
}
