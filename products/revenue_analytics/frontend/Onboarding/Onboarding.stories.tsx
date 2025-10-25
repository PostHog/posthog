import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useActions } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import externalDataSourceResponseMock from '~/mocks/fixtures/api/projects/team_id/external_data_sources/externalDataSource.json'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

import { Onboarding as RevenueAnalyticsOnboarding } from './Onboarding'

const MOCK_TEAM_WITHOUT_VIEWSET = { ...MOCK_DEFAULT_TEAM, managed_viewsets: { revenue_analytics: false } }

const meta: Meta = {
    component: RevenueAnalyticsOnboarding,
    title: 'Scenes-App/Revenue Analytics/Onboarding',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.revenueAnalytics(),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/external_data_sources/': () => {
                    return [
                        200,
                        {
                            ...EMPTY_PAGINATED_RESPONSE,
                            results: [externalDataSourceResponseMock],
                        },
                    ]
                },
                '/api/environments/:team_id/external_data_sources/wizard': () => {
                    return [
                        200,
                        {
                            Stripe: {
                                name: 'Stripe',
                                iconPath: '/static/services/stripe.png',
                                fields: [],
                                caption: '',
                            },
                        },
                    ]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const Onboarding: Story = { args: { closeOnboarding: () => {} } }
export const OnboardingAddSource: Story = { args: { initialSetupView: 'add-source', closeOnboarding: () => {} } }
export const OnboardingWithViewsetFeatureFlag: StoryFn = () => {
    const { loadCurrentTeamSuccess } = useActions(teamLogic)

    useOnMountEffect(() => {
        loadCurrentTeamSuccess(MOCK_TEAM_WITHOUT_VIEWSET)
    })

    return <RevenueAnalyticsOnboarding closeOnboarding={() => {}} />
}
OnboardingWithViewsetFeatureFlag.parameters = {
    featureFlags: [FEATURE_FLAGS.MANAGED_VIEWSETS],
}
