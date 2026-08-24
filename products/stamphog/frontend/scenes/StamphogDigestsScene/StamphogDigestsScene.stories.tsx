import type { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { DigestChannelApi, DigestRunApi } from '../../generated/api.schemas'

const digestChannels = {
    count: 2,
    next: null,
    previous: null,
    results: [
        {
            id: '00000000-0000-0000-0000-0000000000d1',
            audience_key: 'repo:PostHog/posthog',
            slack_integration_id: 1,
            slack_channel_id: 'C012AB3CD',
            slack_channel_name: 'team-devex',
            resolution_source: 'stamphog_config',
            enabled: true,
            last_digest_at: '2026-08-17T09:00:00Z',
            created_at: '2026-07-01T00:00:00Z',
            updated_at: '2026-08-17T09:00:00Z',
        },
        {
            id: '00000000-0000-0000-0000-0000000000d2',
            audience_key: 'repo:PostHog/hogland',
            slack_integration_id: 1,
            slack_channel_id: 'C045EF6GH',
            slack_channel_name: '',
            resolution_source: 'slack_name_match',
            enabled: true,
            last_digest_at: null,
            created_at: '2026-07-01T00:00:00Z',
            updated_at: '2026-07-01T00:00:00Z',
        },
    ] as DigestChannelApi[],
}

const digestRun = (overrides: Partial<DigestRunApi>): DigestRunApi =>
    ({
        id: '00000000-0000-0000-0000-0000000000e0',
        digest_channel: '00000000-0000-0000-0000-0000000000d1',
        status: 'completed',
        pr_count: 14,
        slack_message_ts: '1755424800.001900',
        error: '',
        created_at: '2026-08-17T09:00:00Z',
        posted_at: '2026-08-17T09:00:04Z',
        ...overrides,
    }) as DigestRunApi

const digestRuns = {
    count: 4,
    next: null,
    previous: null,
    results: [
        digestRun({}),
        // A channel with no slack_channel_name falls back to its ID. This run also found nothing worth
        // summarizing, so it completed with posted_at stamped but never called Slack — only the empty
        // slack_message_ts separates it from a real post.
        digestRun({
            id: '00000000-0000-0000-0000-0000000000e1',
            digest_channel: '00000000-0000-0000-0000-0000000000d2',
            pr_count: 0,
            slack_message_ts: '',
            created_at: '2026-08-17T09:00:01Z',
            posted_at: '2026-08-17T09:00:06Z',
        }),
        digestRun({
            id: '00000000-0000-0000-0000-0000000000e2',
            status: 'failed',
            pr_count: 9,
            slack_message_ts: '',
            error: 'slack_api_error: channel_not_found',
            created_at: '2026-08-16T09:00:00Z',
            posted_at: null,
        }),
        digestRun({
            id: '00000000-0000-0000-0000-0000000000e3',
            status: 'pending',
            pr_count: 0,
            slack_message_ts: '',
            created_at: '2026-08-18T09:00:00Z',
            posted_at: null,
        }),
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Stamphog/Digests',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-08-18 12:00:00',
        pageUrl: urls.stamphogDigests(),
        testOptions: { waitForSelector: '[data-attr="stamphog-digests-channel-filter"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/stamphog/digest_runs/': digestRuns,
                '/api/projects/:team_id/stamphog/digest_channels/': digestChannels,
            },
        }),
    ],
}
export default meta

// Posted, posted-but-empty, failed to reach Slack, and not yet run.
export const DigestsList: StoryObj = {}

export const DigestsListEmpty: StoryObj = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/stamphog/digest_runs/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
            },
        }),
    ],
}
