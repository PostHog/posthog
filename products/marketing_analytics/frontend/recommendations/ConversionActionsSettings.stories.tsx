import { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'

import { OrganizationMembershipLevel } from 'lib/constants'
import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { teamLogic } from 'scenes/teamLogic'

import { mswDecorator } from '~/mocks/browser'

import { ConversionActionsSettings } from './ConversionActionsSettings'

const QUERY_URL = '/api/environments/:team_id/query/MarketingAnalyticsConversionActionsQuery/'

const ACTIONS = {
    results: [
        {
            action: 'customers/1234567890/conversionActions/10',
            name: 'Purchase',
            account: 'Google Ads account 123-456-7890',
            campaignTable: 'example.campaign',
            primaryConversions: 182,
            allConversions: 182,
            recent: true,
        },
        {
            action: 'customers/1234567890/conversionActions/20',
            name: 'Newsletter signup',
            account: 'Google Ads account 123-456-7890',
            campaignTable: 'example.campaign',
            primaryConversions: 0,
            allConversions: 1240,
            recent: true,
        },
    ],
    unmatchedSavedActions: [],
}

const meta: Meta<typeof ConversionActionsSettings> = {
    title: 'Scenes-App/Marketing Analytics/Recommendation conversion actions',
    component: ConversionActionsSettings,
    decorators: [
        mswDecorator({}),
        // The banner and skeletons size to their parent, so the snapshot needs a sized one.
        (Story) => (
            <div className="w-160">
                <Story />
            </div>
        ),
    ],
    parameters: {
        layout: 'padded',
        mockDate: '2025-02-15T12:00:00Z',
        msw: { mocks: { post: { [QUERY_URL]: () => [200, ACTIONS] } } },
    },
}
export default meta
type Story = StoryObj<typeof meta>

export const ForMembers: Story = {
    render: () => {
        const { loadCurrentTeamSuccess } = useActions(teamLogic)
        const { currentTeam } = useValues(teamLogic)
        useDelayedOnMountEffect(() => {
            loadCurrentTeamSuccess({ ...currentTeam!, effective_membership_level: OrganizationMembershipLevel.Member })
        })
        return <ConversionActionsSettings />
    },
    parameters: { testOptions: { waitForSelector: '.LemonCheckbox--disabled' } },
}

export const NoConversionActions: Story = {
    parameters: { msw: { mocks: { post: { [QUERY_URL]: () => [200, { results: [], unmatchedSavedActions: [] }] } } } },
}

export const LoadFailed: Story = {
    parameters: { msw: { mocks: { post: { [QUERY_URL]: () => [500, { detail: 'Query failed' }] } } } },
}

export const Loading: Story = {
    parameters: {
        msw: { mocks: { post: { [QUERY_URL]: () => new Promise(() => {}) } } },
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: '.LemonSkeleton' },
    },
}
