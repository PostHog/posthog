import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Decorator, Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useLayoutEffect, useState } from 'react'

import type { ErrorEventType } from 'lib/components/Errors/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import {
    ErrorTrackingIssueRelease,
    ErrorTrackingQueryResponse,
    ErrorTrackingReleasesQueryResponse,
    NodeKind,
    TrendsQueryResponse,
} from '~/queries/schema/schema-general'

import { errorTrackingQueryResponse, errorTrackingTypeIssue } from './__mocks__/error_tracking_query'
import { TEST_EVENTS } from './__mocks__/events'
import { results as stackFrameResults } from './__mocks__/stack_frames/batch_get'
import { BreakdownPreset } from './components/Breakdowns/consts'
import { miniBreakdownsLogic } from './components/Breakdowns/miniBreakdownsLogic'
import {
    issueFilterPreviewLogic,
    IssueFilterPreview,
    IssueReleasesViewMode,
} from './components/IssueFilterPreview/issueFilterPreviewLogic'
import { errorTrackingIssueSceneLogic } from './scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'

const ISSUE_ID = '01890a1b-2c3d-4e4f-8a9b-0c1d2e3f4a5b'
const FINGERPRINT = String(TEST_EVENTS.javascript_resolved.properties.$exception_fingerprint)
const STORY_FINGERPRINTS = [FINGERPRINT, ...Array.from({ length: 11 }, (_, index) => `story-fingerprint-${index + 1}`)]
const STORY_FINGERPRINT_PROJECTION_RESPONSE = {
    results: STORY_FINGERPRINTS.map((fingerprint, index) => ({
        fingerprint,
        x: Math.cos(index * 1.7) * (1 + (index % 3) * 0.4),
        y: Math.sin(index * 1.7) * (1 + (index % 4) * 0.3),
    })),
    hasMore: false,
}
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
    release_channel: 'stable',
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
const STORY_EMPTY_EVENTS_RESPONSE = {
    columns: ['*', 'timestamp', 'person'],
    hasMore: false,
    results: [],
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
        release_channel: {
            values: [
                { value: 'stable', count: 25 },
                { value: 'beta', count: 9 },
                { value: 'canary', count: 4 },
            ],
            total_count: 38,
        },
    },
}
// Each release is active over a slice of the date range (as fractions), with a volume shape over that slice
const STORY_RELEASES: {
    namespace: string | null
    version: string | null
    build: string | null
    from: number
    to: number
    peak: number
    shape: 'flat' | 'decay' | 'ramp' | 'hump'
}[] = [
    { namespace: 'com.example.app', version: '3.0.4', build: '398', from: 0, to: 1, peak: 2, shape: 'flat' },
    { namespace: 'com.example.app', version: '3.1.0', build: '412', from: 0, to: 0.6, peak: 9, shape: 'decay' },
    { namespace: 'com.example.app', version: '3.1.1', build: '415', from: 0.25, to: 0.85, peak: 14, shape: 'hump' },
    { namespace: 'com.example.app', version: '3.2.0', build: '420', from: 0.65, to: 1, peak: 34, shape: 'ramp' },
    { namespace: 'com.example.app', version: '3.2.1', build: '421', from: 0.88, to: 1, peak: 5, shape: 'flat' },
    { namespace: null, version: null, build: null, from: 0.3, to: 0.5, peak: 1, shape: 'flat' },
]
const STORY_RELEASE_BUCKET_SECONDS = (7 * 24 * 60 * 60) / 40
const STORY_RELEASE_BUCKETS = Array.from({ length: 40 }, (_, index) =>
    new Date(Date.UTC(2024, 6, 2) + index * STORY_RELEASE_BUCKET_SECONDS * 1000).toISOString()
)
function storyReleaseSeries(release: (typeof STORY_RELEASES)[number]): ErrorTrackingIssueRelease {
    const counts = STORY_RELEASE_BUCKETS.map(() => 0)
    const start = Math.floor(release.from * counts.length)
    const end = Math.ceil(release.to * counts.length)
    for (let index = start; index < end; index++) {
        const progress = (index - start) / Math.max(1, end - start - 1)
        const jitter = 0.7 + ((index * 7) % 4) / 10
        const factor = {
            flat: 1,
            decay: 1 - 0.85 * progress,
            ramp: 0.15 + 0.85 * progress,
            hump: Math.sin(Math.PI * progress),
        }[release.shape]
        counts[index] = Math.round(release.peak * factor * jitter)
    }
    const seen = counts.map((count, index) => (count > 0 ? index : -1)).filter((index) => index >= 0)
    return {
        namespace: release.namespace,
        version: release.version,
        build: release.build,
        counts,
        total: counts.reduce((sum, count) => sum + count, 0),
        first_seen: seen.length ? STORY_RELEASE_BUCKETS[seen[0]] : null,
        last_seen: seen.length ? STORY_RELEASE_BUCKETS[seen[seen.length - 1]] : null,
    }
}
function storyReleasesResponse(maxReleases: number): ErrorTrackingReleasesQueryResponse {
    const series = STORY_RELEASES.map(storyReleaseSeries)
    const releases = series.filter((release) => release.namespace !== null).reverse()
    const unattributed = series.find((release) => release.namespace === null) ?? null
    const visible = releases.slice(0, maxReleases)
    const hidden = releases.slice(maxReleases)
    const other = hidden.length
        ? {
              counts: STORY_RELEASE_BUCKETS.map((_, index) =>
                  hidden.reduce((sum, release) => sum + release.counts[index], 0)
              ),
              total: hidden.reduce((sum, release) => sum + release.total, 0),
              first_seen: hidden[0].first_seen,
              last_seen: hidden[0].last_seen,
          }
        : null
    return {
        date_from: STORY_RELEASE_BUCKETS[0],
        date_to: new Date(Date.UTC(2024, 6, 9)).toISOString(),
        buckets: STORY_RELEASE_BUCKETS,
        bucket_seconds: STORY_RELEASE_BUCKET_SECONDS,
        results: visible,
        other,
        other_release_count: hidden.length,
        unattributed,
        release_count: releases.length,
        release_count_truncated: false,
        namespaces: ['com.example.app'],
        total: series.reduce((sum, release) => sum + release.total, 0),
    }
}
const STORY_MANY_CUSTOM_PROPERTIES = Object.fromEntries(
    Array.from({ length: 18 }, (_, index) => [`custom_property_${index + 1}`, `value_${index + 1}`])
)
const STORY_MANY_EVENT_PROPERTIES = JSON.stringify({
    ...JSON.parse(STORY_EVENT_PROPERTIES),
    ...STORY_MANY_CUSTOM_PROPERTIES,
})
const STORY_MANY_BREAKDOWNS_RESPONSE = {
    results: {
        ...STORY_BREAKDOWNS_RESPONSE.results,
        ...Object.fromEntries(
            Object.keys(STORY_MANY_CUSTOM_PROPERTIES).map((property, index) => [
                property,
                {
                    values: [
                        { value: `value_${index + 1}`, count: 20 },
                        { value: 'other', count: 18 },
                    ],
                    total_count: 38,
                },
            ])
        ),
    },
}
Object.assign(STORY_BREAKDOWNS_RESPONSE.results, STORY_MANY_BREAKDOWNS_RESPONSE.results)
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
const STORY_ASSIGNEE_MEMBERS = Array.from({ length: 32 }, (_, index) => {
    const userNumber = index + 1
    const user =
        index === 0
            ? MOCK_DEFAULT_BASIC_USER
            : {
                  id: 1000 + index,
                  uuid: `story-user-${userNumber}`,
                  distinct_id: `story-user-${userNumber}`,
                  first_name: `Engineer ${String(userNumber).padStart(2, '0')}`,
                  email: `engineer-${userNumber}@example.com`,
              }

    return {
        id: `story-member-${userNumber}`,
        user,
        level: 1,
        joined_at: '2024-01-01T00:00:00.000Z',
        updated_at: '2024-01-01T00:00:00.000Z',
        is_2fa_enabled: false,
        has_social_auth: false,
        last_login: '2024-07-08T00:00:00.000Z',
    }
})
const STORY_ASSIGNEE_ROLES = Array.from({ length: 16 }, (_, index) => {
    const roleId = `story-role-${index + 1}`
    const includesCurrentUser = index % 5 === 0

    return {
        id: roleId,
        name: `Engineering role ${String(index + 1).padStart(2, '0')}`,
        members: includesCurrentUser
            ? [
                  {
                      id: `story-role-member-${index + 1}`,
                      user: MOCK_DEFAULT_BASIC_USER,
                      role_id: roleId,
                      joined_at: '2024-01-01T00:00:00.000Z',
                      updated_at: '2024-01-01T00:00:00.000Z',
                  },
              ]
            : [],
        created_at: '2024-01-01T00:00:00.000Z',
        created_by: MOCK_DEFAULT_BASIC_USER,
    }
})
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
const STORY_INSIGHT_DAYS = [
    '2024-07-02',
    '2024-07-03',
    '2024-07-04',
    '2024-07-05',
    '2024-07-06',
    '2024-07-07',
    '2024-07-08',
]
const STORY_INSIGHT_LABELS = [
    '2-Jul-2024',
    '3-Jul-2024',
    '4-Jul-2024',
    '5-Jul-2024',
    '6-Jul-2024',
    '7-Jul-2024',
    '8-Jul-2024',
]
const STORY_INSIGHT_DATA: Record<string, number[]> = {
    Exceptions: [18, 24, 16, 31, 22, 27, 19],
    'Issues created': [4, 6, 3, 8, 5, 7, 4],
    'Affected users': [12, 15, 11, 21, 14, 18, 13],
    'Crash-free sessions %': [98.8, 98.2, 99.1, 97.6, 98.5, 97.9, 98.7],
}

function buildStoryInsightResponse(label: string): TrendsQueryResponse {
    const data = STORY_INSIGHT_DATA[label] ?? []
    return {
        results: [
            {
                action:
                    label === 'Crash-free sessions %'
                        ? null
                        : { id: '$exception', type: 'events', name: label, order: 0 },
                order: 0,
                label,
                count: data.reduce((sum, value) => sum + value, 0),
                aggregated_value: data.reduce((sum, value) => sum + value, 0),
                data,
                labels: STORY_INSIGHT_LABELS,
                days: STORY_INSIGHT_DAYS,
            },
        ],
    }
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
                        logs_session_id_attribute_keys: ['sessionId'],
                    },
                ],
                '/api/environments/:team_id/error_tracking/issues/exists/': [200, { exists: true }],
                '/api/environments/:team_id/error_tracking/issues/:id/': [200, STORY_ISSUE],
                '/api/environments/:team_id/error_tracking/fingerprints': [
                    200,
                    {
                        next: null,
                        results: STORY_FINGERPRINTS.map((fingerprint, index) => ({
                            fingerprint,
                            issue_id: ISSUE_ID,
                            created_at: STORY_TIMESTAMPS[index % STORY_TIMESTAMPS.length],
                        })),
                    },
                ],
                '/api/environments/:team_id/error_tracking/spike_events': [200, { results: [] }],
                // Empty keeps this story's snapshot unchanged; the populated section has its own story.
                '/api/projects/:team_id/signals/reports/': [200, { next: null, results: [] }],
                '/api/projects/:team_id/property_definitions/': [200, STORY_PROPERTY_DEFINITIONS],
                '/api/environments/:team_id/session_recordings/:id/capture_diagnostics/': [
                    200,
                    { properties: { $has_recording: true, $recording_status: 'active' } },
                ],
            },
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const body = (await request.json()) as {
                        query?: { kind?: string; select?: string[]; maxReleases?: number }
                    }
                    if (body.query?.kind === NodeKind.ErrorTrackingBreakdownsQuery) {
                        return [200, STORY_BREAKDOWNS_RESPONSE]
                    }
                    if (body.query?.kind === NodeKind.ErrorTrackingFingerprintProjectionQuery) {
                        return [200, STORY_FINGERPRINT_PROJECTION_RESPONSE]
                    }
                    if (body.query?.kind === NodeKind.EventsQuery) {
                        return body.query.select?.includes('properties.$exception_list')
                            ? [200, STORY_TIMELINE_RESPONSE]
                            : [200, STORY_EVENTS_RESPONSE]
                    }
                    if (body.query?.kind === NodeKind.ErrorTrackingReleasesQuery) {
                        return [200, storyReleasesResponse(body.query.maxReleases ?? 5)]
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

export const InsightsPage: Story = {
    parameters: { pageUrl: urls.errorTracking({ activeTab: 'insights' }) },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const body = (await request.json()) as {
                        query?: {
                            kind?: string
                            series?: { custom_name?: string }[]
                            trendsFilter?: { formulaNodes?: { custom_name?: string }[] }
                        }
                    }
                    if (body.query?.kind === NodeKind.HogQLQuery) {
                        return [200, { results: [[157, 76, 1240, 42]] }]
                    }
                    const label =
                        body.query?.trendsFilter?.formulaNodes?.[0]?.custom_name ??
                        body.query?.series?.[0]?.custom_name ??
                        ''
                    return [200, buildStoryInsightResponse(label)]
                },
            },
        }),
    ],
}

// An unresolved source maps recommendation renders the wizard banner above the
// issue list without the sticky filters bar overlapping its bottom edge
export const ListPageWithSourceMapsBanner: Story = {
    decorators: [
        mswDecorator({
            get: {
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
function IssueScenePreviewStory({
    activePreview,
    selectedEventProperties,
    openBreakdown,
    propertyFilter,
    releasesViewMode,
}: {
    activePreview: IssueFilterPreview
    selectedEventProperties?: string
    openBreakdown?: BreakdownPreset
    propertyFilter?: { key: string; value: string }
    releasesViewMode?: IssueReleasesViewMode
}): JSX.Element {
    const { applyPropertyFilter, setActivePreview, setReleasesViewMode } = useActions(issueFilterPreviewLogic)
    const { selectEvent } = useActions(errorTrackingIssueSceneLogic({ id: ISSUE_ID }))
    const { openBreakdownDetails } = useActions(miniBreakdownsLogic({ issueId: ISSUE_ID }))

    useLayoutEffect(() => {
        setActivePreview(activePreview)
        setReleasesViewMode(releasesViewMode ?? 'list')
        if (selectedEventProperties) {
            selectEvent({
                event: '$exception',
                uuid: STORY_EVENT_UUIDS[0],
                timestamp: STORY_TIMESTAMPS[0],
                distinct_id: STORY_PERSON.distinct_id,
                properties: JSON.parse(selectedEventProperties),
                person: {
                    id: STORY_PERSON.id,
                    distinct_ids: [STORY_PERSON.distinct_id],
                    properties: STORY_PERSON.properties,
                },
            } as ErrorEventType)
        }
        if (openBreakdown) {
            openBreakdownDetails(openBreakdown)
        }
        if (propertyFilter) {
            applyPropertyFilter(propertyFilter.key, propertyFilter.value)
        }
    }, [
        activePreview,
        applyPropertyFilter,
        openBreakdown,
        openBreakdownDetails,
        propertyFilter,
        releasesViewMode,
        selectEvent,
        selectedEventProperties,
        setActivePreview,
        setReleasesViewMode,
    ])

    return <App />
}

function IngestionWarningStory(): JSX.Element | null {
    const { loadCurrentTeamSuccess } = useActions(teamLogic)
    const [ready, setReady] = useState(false)

    useLayoutEffect(() => {
        loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, autocapture_exceptions_opt_in: true })
        setReady(true)
    }, [loadCurrentTeamSuccess])

    return ready ? <App /> : null
}

// A banner renders above the issue list without the sticky filters bar overlapping it.
// Issues have to exist, or the scene's setup empty state takes over and there is no list
// to lay the banner out against.
export const ListPageWithIngestionWarning: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/error_tracking/issues/exists/': () => [200, { exists: true }],
            },
        }),
    ],
    render: () => <IngestionWarningStory />,
}
export const GroupPage: Story = {
    name: 'Issue scene',
    parameters: { pageUrl: urls.errorTrackingIssue(ISSUE_ID) },
}

export const GroupPageManyAssignees: Story = {
    name: 'Issue scene with many assignees',
    parameters: { pageUrl: urls.errorTrackingIssue(ISSUE_ID) },
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/:organization_id/members': ({ request }) => {
                    const search = new URL(request.url).searchParams.get('search')?.toLowerCase()
                    const members = search
                        ? STORY_ASSIGNEE_MEMBERS.filter((member) =>
                              [member.user.first_name, member.user.email].some((value) =>
                                  value.toLowerCase().includes(search)
                              )
                          )
                        : STORY_ASSIGNEE_MEMBERS

                    return [
                        200,
                        {
                            count: members.length,
                            results: members,
                            next: null,
                            previous: null,
                        },
                    ]
                },
                '/api/organizations/:organization_id/roles/': [
                    200,
                    {
                        count: STORY_ASSIGNEE_ROLES.length,
                        results: STORY_ASSIGNEE_ROLES,
                        next: null,
                        previous: null,
                    },
                ],
            },
        }),
    ],
}

export const GroupPageContentSizedBreakdownPanel: Story = {
    name: 'Issue scene with content-sized breakdown panel',
    parameters: { pageUrl: urls.errorTrackingIssue(ISSUE_ID) },
    render: () => <IssueScenePreviewStory activePreview="properties" />,
}

export const GroupPageCappedBreakdownPanel: Story = {
    name: 'Issue scene with capped breakdown panel',
    parameters: { pageUrl: urls.errorTrackingIssue(ISSUE_ID) },
    render: () => (
        <IssueScenePreviewStory activePreview="properties" selectedEventProperties={STORY_MANY_EVENT_PROPERTIES} />
    ),
}

export const GroupPageFingerprintMap: Story = {
    name: 'Issue scene with fingerprint map',
    parameters: {
        pageUrl: urls.errorTrackingIssue(ISSUE_ID),
        featureFlags: [FEATURE_FLAGS.ERROR_TRACKING_FINGERPRINT_MAP],
    },
    render: () => <IssueScenePreviewStory activePreview="fingerprints" />,
}

export const GroupPageReleases: Story = {
    name: 'Issue scene with releases',
    parameters: {
        pageUrl: urls.errorTrackingIssue(ISSUE_ID),
        featureFlags: [FEATURE_FLAGS.ERROR_TRACKING_ISSUE_RELEASES],
    },
    render: () => <IssueScenePreviewStory activePreview="releases" />,
}

export const GroupPageReleasesStacked: Story = {
    name: 'Issue scene with stacked releases',
    parameters: {
        pageUrl: urls.errorTrackingIssue(ISSUE_ID),
        featureFlags: [FEATURE_FLAGS.ERROR_TRACKING_ISSUE_RELEASES],
    },
    render: () => <IssueScenePreviewStory activePreview="releases" releasesViewMode="stacked" />,
}

export const GroupPageBreakdownLoading: Story = {
    name: 'Issue scene with loading breakdown panel',
    parameters: {
        pageUrl: urls.errorTrackingIssue(ISSUE_ID),
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const body = (await request.json()) as { query?: { kind?: string; select?: string[] } }
                    if (body.query?.kind === NodeKind.ErrorTrackingBreakdownsQuery) {
                        return new Promise<never>(() => {})
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
            },
        }),
    ],
    render: () => <IssueScenePreviewStory activePreview="properties" />,
}

export const GroupPageBreakdownModal: Story = {
    name: 'Issue scene with breakdown modal',
    parameters: { pageUrl: urls.errorTrackingIssue(ISSUE_ID) },
    render: () => (
        <IssueScenePreviewStory activePreview="properties" openBreakdown={{ property: '$browser', title: 'Browser' }} />
    ),
}

export const GroupPageBreakdownModalLoading: Story = {
    name: 'Issue scene with loading breakdown modal',
    parameters: {
        pageUrl: urls.errorTrackingIssue(ISSUE_ID),
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const body = (await request.json()) as {
                        query?: { kind?: string; select?: string[]; maxValuesPerProperty?: number }
                    }
                    if (
                        body.query?.kind === NodeKind.ErrorTrackingBreakdownsQuery &&
                        body.query.maxValuesPerProperty === 100
                    ) {
                        return new Promise<never>(() => {})
                    }
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
            },
        }),
    ],
    render: () => (
        <IssueScenePreviewStory activePreview="properties" openBreakdown={{ property: '$browser', title: 'Browser' }} />
    ),
}

export const GroupPageEmptyWithFilter: Story = {
    name: 'Issue scene with no matching exceptions',
    parameters: { pageUrl: urls.errorTrackingIssue(ISSUE_ID) },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const body = (await request.json()) as { query?: { kind?: string; select?: string[] } }
                    if (body.query?.kind === NodeKind.ErrorTrackingBreakdownsQuery) {
                        return [200, STORY_BREAKDOWNS_RESPONSE]
                    }
                    if (body.query?.kind === NodeKind.EventsQuery) {
                        return body.query.select?.includes('properties.$exception_list')
                            ? [200, STORY_TIMELINE_RESPONSE]
                            : [200, STORY_EMPTY_EVENTS_RESPONSE]
                    }
                    return body.query?.kind === NodeKind.HogQLQuery
                        ? [200, { results: [] }]
                        : [200, STORY_SUMMARY_RESPONSE]
                },
            },
        }),
    ],
    render: () => <IssueScenePreviewStory activePreview="time" propertyFilter={{ key: '$browser', value: 'Chrome' }} />,
}

export const GroupPageLoading: Story = {
    name: 'Issue scene loading',
    parameters: {
        pageUrl: urls.errorTrackingIssue(ISSUE_ID),
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': () => new Promise<never>(() => {}),
            },
        }),
    ],
}

function selfDrivingReportsDecorator(count: number): Decorator {
    return mswDecorator({
        get: {
            '/api/projects/:team_id/signals/reports/': () => [
                200,
                {
                    next: null,
                    results: Array.from({ length: count }, (_, index) => ({
                        id: `019f9582-93e7-77c1-8912-4f541d70cb${String(index).padStart(2, '0')}`,
                        status: index % 2 === 0 ? 'ready' : 'resolved',
                        title: `fix(replay): guard against a missing snapshot index (${index + 1})`,
                        summary: 'The player throws when a recording ends on a snapshot the index never received.',
                        implementation_pr_url: `https://github.com/PostHog/posthog/pull/${64772 + index}`,
                        implementation_pr_merged: index % 2 === 1,
                        updated_at: '2024-07-08T21:00:00Z',
                    })),
                },
            ],
        },
    })
}

// Self-driving investigated this issue, so its section renders in the right pane above the exception
// card. This is the only coverage of the placement: the section's own story fabricates a pane around
// it, so it cannot show that the two header strips line up, that the section paints the background the
// pane leaves unpainted, or that a single border separates the two.
export const GroupPageWithSelfDriving: Story = {
    name: 'Issue scene with self-driving',
    parameters: {
        pageUrl: urls.errorTrackingIssue(ISSUE_ID),
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/reports/': () => [
                    200,
                    {
                        next: null,
                        results: [
                            {
                                id: '019f9582-93e7-77c1-8912-4f541d70cb13',
                                status: 'ready',
                                title: 'fix(replay): guard against a missing snapshot index',
                                summary:
                                    'The player throws when a recording ends on a snapshot the index never received.',
                                implementation_pr_url: 'https://github.com/PostHog/posthog/pull/64772',
                                implementation_pr_merged: false,
                                updated_at: '2024-07-08T21:00:00Z',
                            },
                            {
                                id: '019f954a-8ed0-7a18-a198-3ffed1a2def0',
                                status: 'resolved',
                                title: 'fix(replay): stop dropping events after a tab regains focus',
                                summary: 'Events queued while the tab was hidden are discarded when it regains focus.',
                                implementation_pr_url: 'https://github.com/PostHog/posthog/pull/64773',
                                implementation_pr_merged: true,
                                updated_at: '2024-07-08T15:00:00Z',
                            },
                        ],
                    },
                ],
            },
        }),
    ],
}

// An issue the agent looked at many times. The section stops at half the pane and scrolls, so the
// exception card and its stack trace stay on screen.
export const GroupPageWithManySelfDrivingReports: Story = {
    name: 'Issue scene with many self-driving reports',
    parameters: {
        pageUrl: urls.errorTrackingIssue(ISSUE_ID),
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [selfDrivingReportsDecorator(12)],
}
