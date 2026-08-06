import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useLayoutEffect, useState } from 'react'

import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
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
                // Exceptions have been ingested — the scene shows the issue list rather than the setup prompt
                'api/environments/:team_id/error_tracking/issues/exists': () => [200, { exists: true }],
                'api/environments/:team_id/error_tracking/spike_events': () => [200, { count: 0, results: [] }],
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
// Autocapture must be on for the issue list to render instead of the full setup prompt,
// and it comes from the bootstrap app context, so an msw override isn't enough
function IngestionWarningStory(): JSX.Element | null {
    const { loadCurrentTeamSuccess } = useActions(teamLogic)
    const [ready, setReady] = useState(false)

    useLayoutEffect(() => {
        loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, autocapture_exceptions_opt_in: true })
        setReady(true)
    }, [loadCurrentTeamSuccess])

    return ready ? <App /> : null
}

// No exceptions ingested yet, but autocapture enabled — the ingestion warning banner
// renders above the issue list without the sticky filters bar overlapping it
export const ListPageWithIngestionWarning: Story = {
    decorators: [
        mswDecorator({
            get: {
                'api/environments/:team_id/error_tracking/issues/exists': () => [200, { exists: false }],
            },
        }),
    ],
    render: () => <IngestionWarningStory />,
}
export const GroupPage: Story = { parameters: { pageUrl: urls.errorTrackingIssue('id') } }
