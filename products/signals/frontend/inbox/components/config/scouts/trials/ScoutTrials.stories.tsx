import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import { ScoutTrials } from './ScoutTrials'
import { createScoutTrialsStoryMocks } from './scoutTrialsStoryMocks'

const trialMocks = createScoutTrialsStoryMocks()

const meta: Meta<typeof ScoutTrials> = {
    id: 'scenes-app-inbox-scout-comparisons-interactive',
    title: 'Scenes-App/Inbox/Scout trials interactive',
    component: ScoutTrials,
    parameters: { layout: 'fullscreen', testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        (Story) => {
            useEffect(() => {
                teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 2 })
                userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, id: 42, is_staff: true })
            }, [])
            return <Story />
        },
        mswDecorator(trialMocks.mocks),
    ],
}
export default meta
type Story = StoryObj<typeof ScoutTrials>

export const Interactive: Story = {}
export const Running: Story = {
    decorators: [mswDecorator(trialMocks.runningMocks)],
}
