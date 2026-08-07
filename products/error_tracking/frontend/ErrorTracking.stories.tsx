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
// Scoped to the list stories: GroupPage lacks the mocks its real content needs,
// so unmasking it via the setup-prompt gate at meta level renders a blank page
const listPageMocks = {
    get: {
        // Exceptions have been ingested — the scene shows the issue list rather than the setup prompt
        'api/environments/:team_id/error_tracking/issues/exists': () => [200, { exists: true }],
        'api/environments/:team_id/error_tracking/spike_events': () => [200, { count: 0, results: [] }],
    },
}

export const ListPage: Story = { decorators: [mswDecorator(listPageMocks)] }

// An unresolved source maps recommendation renders the wizard banner above the
// issue list without the sticky filters bar overlapping its bottom edge
export const ListPageWithSourceMapsBanner: Story = {
    decorators: [
        mswDecorator({
            get: {
                ...listPageMocks.get,
                'api/environments/:team_id/error_tracking/recommendations': () => [
                    200,
                    {
                        results: [
                            {
                                id: 'source-maps-recommendation',
                                type: 'source_maps',
                                completed: false,
                                status: 'ready',
                                computed_at: '2024-07-08T00:00:00Z',
                                dismissed_at: null,
                                created_at: '2024-07-08T00:00:00Z',
                                updated_at: '2024-07-08T00:00:00Z',
                                meta: {
                                    total_frames: 100,
                                    unresolved_frames: 62,
                                    unresolved_pct: 0.62,
                                    threshold_pct: 0.25,
                                    min_sample_frames: 50,
                                    lookback_hours: 24,
                                },
                            },
                        ],
                    },
                ],
            },
        }),
    ],
}
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
                ...listPageMocks.get,
                'api/environments/:team_id/error_tracking/issues/exists': () => [200, { exists: false }],
            },
        }),
    ],
    render: () => <IngestionWarningStory />,
}
export const GroupPage: Story = { parameters: { pageUrl: urls.errorTrackingIssue('id') } }
