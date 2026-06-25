import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import {
    errorTrackingEventsQueryResponse,
    errorTrackingQueryResponse,
    errorTrackingTypeIssue,
} from './__mocks__/error_tracking_query'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/ErrorTracking',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-07-09', // To stabilize relative dates
        pageUrl: urls.errorTracking(),
        testOptions: { viewport: { width: 1300, height: 2000 } },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/error_tracking/issue/:id': () => [200, errorTrackingTypeIssue],
            },
            post: {
                '/api/environments/:team_id/query/ErrorTrackingQuery': () => [200, errorTrackingQueryResponse],
                '/api/environments/:team_id/query/EventsQuery': () => [200, errorTrackingEventsQueryResponse],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const ListPage: Story = {}
export const GroupPage: Story = { parameters: { pageUrl: urls.errorTrackingIssue('id') } }
