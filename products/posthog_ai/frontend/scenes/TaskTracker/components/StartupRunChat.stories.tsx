import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { SidePanelRunner } from '../../../components/SidePanelRunner'
import { runStreamLogic } from '../../../logics/runStreamLogic'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'

function StartupSidebar(): JSX.Element {
    const { setActiveCreation } = useActions(taskTrackerSceneLogic({ panelId: 'startup-story' }))
    const { startOptimisticRun } = useActions(runStreamLogic({ streamKey: 'startup-story' }))
    useEffect(() => {
        setActiveCreation({ streamKey: 'startup-story' })
        startOptimisticRun('Explain how to measure weekly active users.')
    }, [setActiveCreation, startOptimisticRun])
    return (
        <div className="flex h-160 w-100 flex-col border rounded bg-surface-primary">
            <div className="px-4 py-3 font-semibold">PostHog AI</div>
            <div className="flex-1 min-h-0">
                <SidePanelRunner panelId="startup-story" />
            </div>
        </div>
    )
}

const meta: Meta = {
    title: 'Products/PostHog AI/Startup chat',
    render: () => <StartupSidebar />,
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        mswDecorator({
            get: {
                '/api/code/invites/check-access/': { has_access: true },
                '/api/projects/:team/tasks/': { results: [], count: 0 },
                '/api/projects/:team/tasks/repositories/': { repositories: [] },
                '/api/projects/:team/tasks/@me/config/': { ai_run_preferences: {}, resolved_ai_run_defaults: {} },
                '/api/environments/:team/integrations/': { results: [] },
            },
        }),
    ],
}
export default meta

export const Sidebar: StoryObj = {}
