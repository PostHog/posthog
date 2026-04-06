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
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/error_tracking/issue/:id': async (_, res, ctx) => {
                    return res(ctx.json(errorTrackingTypeIssue))
                },
            },
            post: {
                '/api/environments/:team_id/query/ErrorTrackingQuery': async (_, res, ctx) =>
                    res(ctx.json(errorTrackingQueryResponse)),
                '/api/environments/:team_id/query/EventsQuery': async (_, res, ctx) =>
                    res(ctx.json(errorTrackingEventsQueryResponse)),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const ListPage: Story = {}
export const GroupPage: Story = { parameters: { pageUrl: urls.errorTrackingIssue('id') } }
