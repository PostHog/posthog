import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { ErrorTrackingQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import { errorTrackingQueryResponse, errorTrackingTypeIssue } from './__mocks__/error_tracking_query'
import { TEST_EVENTS } from './__mocks__/events'
import { results as stackFrameResults } from './__mocks__/stack_frames/batch_get'

const ISSUE_ID = 'issue-id'
const FINGERPRINT = String(TEST_EVENTS.javascript_resolved.properties.$exception_fingerprint)
const STORY_STACK_FRAME_RESULTS = stackFrameResults.map((record) => ({
    ...record,
    raw_id: record.raw_id.includes('/') ? record.raw_id : `${record.raw_id}/0`,
}))
const STORY_TIMESTAMPS = [
    '2024-07-08T15:42:00.000Z',
    '2024-07-08T13:18:00.000Z',
    '2024-07-08T09:05:00.000Z',
    '2024-07-07T21:51:00.000Z',
    '2024-07-07T16:27:00.000Z',
    '2024-07-07T11:03:00.000Z',
    '2024-07-06T18:34:00.000Z',
    '2024-07-06T08:12:00.000Z',
]
const STORY_EVENT_UUIDS = STORY_TIMESTAMPS.map((_, index) => `story-event-${index}`)
const STORY_EVENT_PROPERTIES = JSON.stringify({
    ...TEST_EVENTS.javascript_resolved.properties,
    $exception_fingerprint: FINGERPRINT,
})
const STORY_EXCEPTION_LIST = TEST_EVENTS.javascript_resolved.properties.$exception_list
const STORY_TIMELINE_RESPONSE = {
    results: STORY_TIMESTAMPS.map((timestamp, index) => [
        STORY_EVENT_UUIDS[index],
        '$exception',
        timestamp,
        'web',
        null,
        STORY_EXCEPTION_LIST,
        FINGERPRINT,
        ISSUE_ID,
    ]),
}
const STORY_PERSON = {
    id: 'story-person',
    uuid: 'story-person',
    distinct_id: 'story-person',
    created_at: '2024-07-01T10:00:00.000Z',
    properties: { email: 'developer@example.com' },
}
const STORY_EVENTS_RESPONSE = {
    columns: ['*', 'timestamp', 'person'],
    hasMore: false,
    results: STORY_TIMESTAMPS.map((timestamp, index) => [
        {
            uuid: STORY_EVENT_UUIDS[index],
            event: '$exception',
            distinct_id: STORY_PERSON.distinct_id,
            properties: JSON.parse(STORY_EVENT_PROPERTIES),
        },
        timestamp,
        STORY_PERSON,
    ]),
}
const STORY_BREAKDOWNS_RESPONSE = {
    results: {
        $browser: {
            values: [
                { value: 'Chrome', count: 24 },
                { value: 'Firefox', count: 9 },
                { value: 'Safari', count: 5 },
            ],
            total_count: 38,
        },
        $device_type: {
            values: [
                { value: 'Desktop', count: 30 },
                { value: 'Mobile', count: 8 },
            ],
            total_count: 38,
        },
        $os: {
            values: [
                { value: 'Mac OS X', count: 20 },
                { value: 'Windows', count: 12 },
                { value: 'Linux', count: 6 },
            ],
            total_count: 38,
        },
        $pathname: {
            values: [
                { value: '/billing', count: 19 },
                { value: '/settings', count: 11 },
                { value: '/dashboard', count: 8 },
            ],
            total_count: 38,
        },
        $user_id: {
            values: [
                { value: 'user-101', count: 16 },
                { value: 'user-205', count: 12 },
                { value: 'user-309', count: 10 },
            ],
            total_count: 38,
        },
        $ip: {
            values: [
                { value: '192.0.2.10', count: 18 },
                { value: '198.51.100.20', count: 12 },
                { value: '203.0.113.30', count: 8 },
            ],
            total_count: 38,
        },
        $current_url: {
            values: [
                { value: 'https://example.com/billing', count: 21 },
                { value: 'https://example.com/settings', count: 11 },
                { value: 'https://example.com/dashboard', count: 6 },
            ],
            total_count: 38,
        },
    },
}
const STORY_PROPERTY_DEFINITIONS = {
    count: 2,
    next: null,
    previous: null,
    results: [
        {
            id: 'current-url',
            name: '$current_url',
            description: 'The current URL of the page',
            property_type: 'String',
            type: 1,
            verified: true,
        },
        {
            id: 'plan',
            name: 'plan',
            description: 'The account plan',
            property_type: 'String',
            type: 1,
            verified: false,
        },
    ],
}
const STORY_POSITION_EVENT = {
    uuid: STORY_EVENT_UUIDS[0],
    distinct_id: STORY_PERSON.distinct_id,
    timestamp: STORY_TIMESTAMPS[0],
    properties: STORY_EVENT_PROPERTIES,
}
const STORY_ISSUE = {
    ...errorTrackingTypeIssue,
    id: ISSUE_ID,
    name: 'Non-OK response',
    description: 'The billing request returned an unsuccessful response.',
    first_seen: STORY_TIMESTAMPS.at(-1)!,
}
const STORY_SUMMARY_RESPONSE: ErrorTrackingQueryResponse = {
    ...errorTrackingQueryResponse,
    results: [
        {
            ...errorTrackingQueryResponse.results[0],
            ...STORY_ISSUE,
            first_seen: STORY_TIMESTAMPS.at(-1)!,
            last_seen: STORY_TIMESTAMPS[0],
            first_event: {
                ...STORY_POSITION_EVENT,
                uuid: STORY_EVENT_UUIDS.at(-1)!,
                timestamp: STORY_TIMESTAMPS.at(-1)!,
            },
            last_event: STORY_POSITION_EVENT,
            aggregations: {
                occurrences: 38,
                sessions: 21,
                users: 8,
                volume_buckets: Array.from({ length: 32 }, (_, index) => ({
                    label: new Date(Date.UTC(2024, 6, 2, index * 5)).toISOString(),
                    value: [0, 1, 2, 1, 3, 5, 2, 4][index % 8],
                })),
            },
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/ErrorTracking',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-07-09', // To stabilize relative dates
        pageUrl: urls.errorTracking(),
        testOptions: { viewport: { width: 1440, height: 1000 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/:organization_id/product_push_campaign/active/': [204, null],
                '/api/environments/:team_id/health_issues/summary/': [200, {}],
                '/api/projects/:team_id/logs_config/': [
                    200,
                    {
                        logs_distinct_id_attribute_key: 'posthogDistinctId',
                        logs_distinct_id_attribute_keys: ['posthogDistinctId'],
                        logs_session_id_attribute_keys: ['posthogSessionId'],
                    },
                ],
                '/api/environments/:team_id/error_tracking/issues/exists/': [200, { exists: true }],
                '/api/environments/:team_id/error_tracking/issues/:id/': [200, STORY_ISSUE],
                '/api/environments/:team_id/error_tracking/fingerprints': [
                    200,
                    {
                        next: null,
                        results: [
                            {
                                fingerprint: FINGERPRINT,
                                issue_id: ISSUE_ID,
                                created_at: STORY_TIMESTAMPS.at(-1),
                            },
                        ],
                    },
                ],
                '/api/environments/:team_id/error_tracking/spike_events': [200, { results: [] }],
                '/api/projects/:team_id/property_definitions/': [200, STORY_PROPERTY_DEFINITIONS],
                '/api/environments/:team_id/session_recordings/:id/capture_diagnostics/': [
                    200,
                    { properties: { $has_recording: true, $recording_status: 'active' } },
                ],
            },
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const body = (await request.json()) as { query?: { kind?: string; select?: string[] } }
                    if (body.query?.kind === NodeKind.ErrorTrackingBreakdownsQuery) {
                        return [200, STORY_BREAKDOWNS_RESPONSE]
                    }
                    if (body.query?.kind === NodeKind.EventsQuery) {
                        return body.query.select?.includes('properties.$exception_list')
                            ? [200, STORY_TIMELINE_RESPONSE]
                            : [200, STORY_EVENTS_RESPONSE]
                    }
                    return body.query?.kind === NodeKind.HogQLQuery
                        ? [200, { results: [] }]
                        : [200, STORY_SUMMARY_RESPONSE]
                },
                '/api/environments/:team_id/error_tracking/stack_frames/batch_get/': [
                    200,
                    { results: STORY_STACK_FRAME_RESULTS },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const ListPage: Story = {}
export const GroupPage: Story = {
    name: 'Issue scene',
    parameters: { pageUrl: urls.errorTrackingIssue(ISSUE_ID) },
}
