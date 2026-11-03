import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { mswDecorator } from '~/mocks/browser'

import { AdaptiveIngestionSetting } from './AdaptiveIngestionSetting'

function NewProjectSettingStory(): JSX.Element {
    useEffect(() => {
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
    }, [])

    return (
        <div className="max-w-lg p-6">
            <AdaptiveIngestionSetting />
        </div>
    )
}

const meta: Meta<typeof NewProjectSettingStory> = {
    title: 'ErrorTracking/Adaptive ingestion setting',
    component: NewProjectSettingStory,
    parameters: {
        testOptions: { waitForSelector: '[data-attr="adaptive-ingestion-toggle"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/error_tracking/settings/retrieve_settings/': { adaptive_ingestion_enabled: true },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof NewProjectSettingStory>

export const NewProject: Story = {}
