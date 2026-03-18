import { range, uuid } from 'lib/utils'

import { ErrorTrackingQueryResponse, ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

const eventProperties = JSON.stringify({
    $os: 'Mac OS X',
    $os_version: '10.15.7',
    $browser: 'Chrome',
    $device_type: 'Desktop',
    $host: 'us.posthog.com',
    distinct_id: 'person_id',
    $exception_message: "Cannot read properties of undefined (reading 'onLCP')",
    $exception_type: 'TypeError',
    $exception_fingerprint: 'fingerprint',
    $exception_personURL: 'https://us.posthog.com/project/:id/person/:person_id',
    $exception_level: 'error',
    $sentry_event_id: '790b4d4b9ec6430fb88f18ba2dc7e7c4',
    $sentry_exception: {
        values: [
            {
                type: 'TypeError',
                value: "Cannot read properties of undefined (reading 'onLCP')",
                stacktrace: {
                    frames: [
                        {
                            filename: 'https://app-static-prod.posthog.com/static/chunk-WH2L43MJ.js',
                            function: 'i.onerror',
                            in_app: true,
                            lineno: 18,
                            colno: 76906,
                        },
                        {
                            filename: 'https://app-static-prod.posthog.com/static/chunk-WH2L43MJ.js',
                            function: '?',
                            in_app: true,
                            lineno: 18,
                            colno: 119038,
                        },
                        {
                            filename: 'https://app-static-prod.posthog.com/static/chunk-WH2L43MJ.js',
                            function: '?',
                            in_app: true,
                            lineno: 18,
                            colno: 117937,
                        },
                    ],
                },
                mechanism: {
                    type: 'onerror',
                    handled: false,
                },
            },
        ],
    },
    $sentry_exception_message: "Cannot read properties of undefined (reading 'onLCP')",
    $sentry_exception_type: 'TypeError',
    $level: 'error',
    $sentry_url: 'https://sentry.io/organizations/posthog/issues/?project=project_id&query=issue_id',
    $lib_rate_limit_remaining_tokens: 83.04999999999998,
    $sent_at: '2024-07-08T02:22:02.233000+00:00',
    $geoip_city_name: 'Singapore',
    $geoip_country_name: 'Singapore',
    $geoip_country_code: 'SG',
    $sentry_exception__values__0__type: 'TypeError',
    $sentry_exception__values__0__value: "Cannot read properties of undefined (reading 'onLCP')",
    $sentry_exception__values__0__stacktrace__frames__0__filename:
        'https://app-static-prod.posthog.com/static/chunk-WH2L43MJ.js',
    $sentry_exception__values__0__stacktrace__frames__0__function: 'i.onerror',
    $sentry_exception__values__0__stacktrace__frames__0__in_app: true,
    $sentry_exception__values__0__stacktrace__frames__0__lineno: 18,
    $sentry_exception__values__0__stacktrace__frames__0__colno: 76906,
    $sentry_exception__values__0__stacktrace__frames__1__filename:
        'https://app-static-prod.posthog.com/static/chunk-WH2L43MJ.js',
    $sentry_exception__values__0__stacktrace__frames__1__function: '?',
    $sentry_exception__values__0__stacktrace__frames__1__in_app: true,
    $sentry_exception__values__0__stacktrace__frames__1__lineno: 18,
    $sentry_exception__values__0__stacktrace__frames__1__colno: 119038,
    $sentry_exception__values__0__stacktrace__frames__2__filename:
        'https://app-static-prod.posthog.com/static/chunk-WH2L43MJ.js',
    $sentry_exception__values__0__stacktrace__frames__2__function: '?',
    $sentry_exception__values__0__stacktrace__frames__2__in_app: true,
    $sentry_exception__values__0__stacktrace__frames__2__lineno: 18,
    $sentry_exception__values__0__stacktrace__frames__2__colno: 117937,
    $sentry_exception__values__0__mechanism__type: 'onerror',
    $sentry_exception__values__0__mechanism__handled: false,
    '$sentry_tags__PostHog Person URL': 'https://us.posthog.com/project/:project_id/person/:person_id',
    '$sentry_tags__PostHog Recording URL': 'https://us.posthog.com/project/:project_id/replay/:recording_id',
})

const errorTrackingTypeIssue: ErrorTrackingRelationalIssue = {
    id: uuid(),
    name: 'TypeError',
    description: 'This is a TypeError',
    assignee: null,
    status: 'active',
    first_seen: '2023-07-07T00:00:00.000000-00:00',
    external_issues: [],
}

const errorTrackingGenericIssue: ErrorTrackingRelationalIssue = {
    id: uuid(),
    name: 'Error',
    description: 'This is an Error',
    assignee: null,
    status: 'active',
    first_seen: '2023-07-07T00:00:00.000000-00:00',
    external_issues: [],
}

const errorTrackingQueryResponse: ErrorTrackingQueryResponse = {
    columns: ['occurrences', 'sessions', 'users', 'last_seen', 'first_seen', 'description', 'fingerprint', 'volume'],
    hasMore: false,
    results: [
        {
            ...errorTrackingTypeIssue,
            occurrences: 1000,
            sessions: 750,
            users: 500,
            function: '<anonymous>',
            source: 'path/file.py',
        },
        {
            ...errorTrackingGenericIssue,
            occurrences: 6,
            sessions: 3,
            users: 1,
        },
    ].map(({ occurrences, sessions, users, ...props }) => ({
        ...props,
        last_seen: '2024-07-07T00:00:00.000000-00:00',
        library: 'web',
        aggregations: {
            occurrences: occurrences,
            sessions: sessions,
            users: users,
            volume_buckets: new Array(24).fill({ label: new Date().toISOString(), value: 0 }),
        },
    })),
}

const errorTrackingEventsQueryResponse = {
    columns: ['uuid', 'properties', 'timestamp', 'person'],
    hasMore: false,
    results: range(20).map((index) => [
        `event_uuid_${index}`,
        eventProperties,
        '2024-07-07T00:00:00.000000-00:00',
        {
            created_at: '2024-04-05T21:14:16.048000Z',
            distinct_id: 'BTQiT390vxwlLeDSwZAZpXC7r7bkNc3TQuhobit0oj7',
            properties: { email: 'test@example.com' },
            uuid: 'person_uuid',
        },
    ]),
}

export { errorTrackingEventsQueryResponse, errorTrackingQueryResponse, errorTrackingTypeIssue }
