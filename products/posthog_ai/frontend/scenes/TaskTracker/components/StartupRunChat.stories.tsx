import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'

import { SidePanelRunner } from '../../../components/SidePanelRunner'
import { runInteractionLogic } from '../../../logics/runInteractionLogic'
import { runStreamLogic } from '../../../logics/runStreamLogic'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'

function StartupSidebar({ narrow = true, queued = false }: { narrow?: boolean; queued?: boolean }): JSX.Element {
    const { setActiveCreation } = useActions(taskTrackerSceneLogic({ panelId: 'startup-story' }))
    const { startOptimisticRun } = useActions(runStreamLogic({ streamKey: 'startup-story' }))
    const { enqueueMessage } = useActions(
        runInteractionLogic({
            taskId: '',
            runId: '',
            streamKey: 'startup-story',
            interactionKey: 'startup-story',
            currentRuntimeAdapter: 'claude',
        })
    )
    useEffect(() => {
        setActiveCreation({ streamKey: 'startup-story', interactionKey: 'startup-story' })
        startOptimisticRun('Explain how to measure weekly active users.')
        if (queued) {
            enqueueMessage('Include a monthly comparison and explain how to interpret the result.')
        }
    }, [setActiveCreation, startOptimisticRun, enqueueMessage, queued])
    return (
        <div className={`flex h-160 flex-col border rounded bg-surface-primary ${narrow ? 'w-100' : 'w-180'}`}>
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
                '/api/projects/:team/integrations/': { results: [] },
            },
        }),
    ],
}
export default meta

export const Sidebar: StoryObj = {}
export const QueuedSidebar: StoryObj = { render: () => <StartupSidebar queued /> }
export const QueuedWide: StoryObj = { render: () => <StartupSidebar queued narrow={false} /> }
