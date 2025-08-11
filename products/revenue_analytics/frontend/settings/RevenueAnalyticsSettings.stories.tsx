import { Meta, StoryObj } from '@storybook/react'
import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'
import { mswDecorator } from '~/mocks/browser'
import DatabaseSchemaQuery from '../__mocks__/DatabaseSchemaQuery.json'
import externalDataSourceResponseMock from '~/mocks/fixtures/api/projects/team_id/external_data_sources/externalDataSource.json'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        featureFlags: [FEATURE_FLAGS.REVENUE_ANALYTICS],
        pageUrl: urls.revenueSettings(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/external_data_sources/': () => {
                    return [
                        200,
                        {
                            ...EMPTY_PAGINATED_RESPONSE,
                            results: [
                                externalDataSourceResponseMock,
                                {
                                    ...externalDataSourceResponseMock,
                                    prefix: 'dev_',
                                    revenue_analytics_enabled: false,
                                },
                            ],
                        },
                    ]
                },
            },
            post: { '/api/environments/:team_id/query': () => [200, DatabaseSchemaQuery] },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const RevenueAnalyticsSettings: Story = {}
