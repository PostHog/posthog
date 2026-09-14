import type { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { DigestRunApi } from '../../generated/api.schemas'

const digestRun = (overrides: Partial<DigestRunApi>): DigestRunApi =>
    ({
        id: '00000000-0000-0000-0000-0000000000e0',
        audience_key: 'repo:PostHog/posthog',
        slack_channel_id: 'C012AB3CD',
        slack_channel_name: 'team-devex',
        resolution_source: 'stamphog_config',
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
        // A run with no slack_channel_name falls back to its ID. This one also found nothing worth
        // summarizing, so it completed with posted_at stamped but never called Slack — only the empty
        // slack_message_ts separates it from a real post.
        digestRun({
            id: '00000000-0000-0000-0000-0000000000e1',
            audience_key: 'repo:PostHog/hogland',
            slack_channel_id: 'C045EF6GH',
            slack_channel_name: '',
            resolution_source: 'slack_name_match',
            pr_count: 0,
            slack_message_ts: '',
            created_at: '2026-08-17T09:00:01Z',
            posted_at: '2026-08-17T09:00:06Z',
        }),
        digestRun({
            id: '00000000-0000-0000-0000-0000000000e2',
            audience_key: 'team-devex',
            slack_channel_id: 'C099ZZ9ZZ',
            slack_channel_name: 'team-devex',
            resolution_source: 'owners_contact',
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
        testOptions: { waitForSelector: '[data-attr="stamphog-digests-table"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/stamphog/digest_runs/': digestRuns,
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
