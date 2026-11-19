import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { EngagementEventsBanner } from './EngagementEventsBanner'

const meta: Meta = {
    title: 'Products/Workflows/EngagementEventsBanner',
    component: EngagementEventsBanner,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

type Story = StoryObj

function CaptureOnStory(): JSX.Element {
    const { loadCurrentTeamSuccess } = useActions(teamLogic)
    useEffect(() => {
        loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            workflows_config: { ...MOCK_DEFAULT_TEAM.workflows_config, capture_workflows_engagement_events: true },
        })
    }, [loadCurrentTeamSuccess])
    return (
        <div className="max-w-[960px]">
            <EngagementEventsBanner />
        </div>
    )
}

export const CaptureOn: Story = {
    render: () => <CaptureOnStory />,
}
