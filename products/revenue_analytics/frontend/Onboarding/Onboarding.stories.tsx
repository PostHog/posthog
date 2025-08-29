import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import externalDataSourceResponseMock from '~/mocks/fixtures/api/projects/team_id/external_data_sources/externalDataSource.json'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

import { Onboarding as RevenueAnalyticsOnboarding } from './Onboarding'

const meta: Meta = {
    component: RevenueAnalyticsOnboarding,
    title: 'Scenes-App/Revenue Analytics/Onboarding',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        featureFlags: [FEATURE_FLAGS.REVENUE_ANALYTICS, FEATURE_FLAGS.MRR_BREAKDOWN_REVENUE_ANALYTICS],
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
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const Onboarding: Story = {}
export const OnboardingAddSource: Story = { args: { initialSetupView: 'add-source' } }
