import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect, userEvent } from 'storybook/test'

import type { CodeReviewApprovalRepositoryApi, DigestRunApi } from '../../generated/api.schemas'
import { DigestHistoryModal } from './DigestHistoryModal'

const EMPTY_SUMMARY: DigestRunApi['summary'] = { headline: '', prs: [] }

const digestRun = (overrides: Partial<DigestRunApi>): DigestRunApi =>
    ({
        id: '00000000-0000-0000-0000-0000000000e0',
        audience_key: 'repo:PostHog/posthog',
        slack_channel_id: 'C012AB3CD',
        slack_channel_name: 'team-devex',
        resolution_source: 'stamphog_config',
        status: 'completed',
        pr_count: 3,
        summary: {
            headline: 'Local test runs reuse the database, and one command now starts the dev stack.',
            prs: [
                {
                    pr_number: 4101,
                    title: 'Reuse the test database between local runs',
                    url: 'https://github.com/example-org/example-repo/pull/4101',
                    author_login: 'jane-example',
                    summary: 'Local pytest runs keep the test database, so a second run skips the schema setup.',
                    repository: 'example-org/example-repo',
                },
                {
                    pr_number: 4117,
                    title: 'Collapse the dev stack start into one command',
                    url: 'https://github.com/example-org/example-repo/pull/4117',
                    author_login: 'sam-example',
                    summary: 'One command now starts the services, waits for them, and runs pending migrations.',
                    repository: 'example-org/example-repo',
                },
                {
                    pr_number: 88,
                    title: 'Print the failing step when setup stops',
                    url: 'https://github.com/example-org/example-tools/pull/88',
                    author_login: 'alex-example',
                    summary: 'Setup errors now name the step that failed instead of a generic exit code.',
                    repository: 'example-org/example-tools',
                },
            ],
        },
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
            summary: EMPTY_SUMMARY,
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
            summary: EMPTY_SUMMARY,
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
            summary: EMPTY_SUMMARY,
            status: 'pending',
            pr_count: 0,
            slack_message_ts: '',
            created_at: '2026-08-18T09:00:00Z',
            posted_at: null,
        }),
    ],
}

const repository = (
    index: number,
    overrides: Partial<CodeReviewApprovalRepositoryApi>
): CodeReviewApprovalRepositoryApi =>
    ({
        id: `00000000-0000-0000-0000-0000000000a${index}`,
        repository: 'example-org/web',
        enabled: true,
        digest_enabled: false,
        review_mode: 'label',
        trigger_label: 'auto-approve',
        routing_mode: 'off',
        user_access_level: 'manager',
        created_at: '2026-08-01T00:00:00Z',
        updated_at: '2026-08-01T00:00:00Z',
        ...overrides,
    }) as CodeReviewApprovalRepositoryApi

const repositories = {
    count: 3,
    next: null,
    previous: null,
    results: [
        repository(1, { repository: 'example-org/api', digest_enabled: true }),
        repository(2, { repository: 'example-org/docs', enabled: false }),
        repository(3, { repository: 'example-org/web' }),
    ],
}

const meta: Meta = {
    component: DigestHistoryModal,
    title: 'Scenes-App/Code review/Digest history',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-08-18 12:00:00',
        pageUrl: combineUrl(urls.codeReview('approval_settings'), { digests: '1' }).url,
        testOptions: { waitForSelector: '[data-attr="stamphog-digests-table"]', snapshotTargetSelector: '.LemonModal' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/code_review/approvals/digests/': digestRuns,
                '/api/projects/:team_id/code_review/approvals/repositories/': repositories,
                '/api/projects/:team_id/code_review/approvals/repositories/available_repositories/': {
                    repositories: [],
                    total_count: 0,
                    has_installation: true,
                },
                '/api/projects/:team_id/code_review/approvals/repositories/install_info/': {
                    app_slug: 'example-app',
                    install_url: 'https://github.com/apps/example-app/installations/new',
                    authorize_url: 'https://github.com/login/oauth/authorize',
                },
            },
        }),
    ],
}
export default meta

// Posted, posted-but-empty, failed to reach Slack, and not yet run.
export const DigestsList: StoryObj = {}

export const DigestExpanded: StoryObj = {
    play: async () => {
        const toggle = await waitFor(() => {
            // The modal renders in a portal outside the story root.
            const button = document.body.querySelector<HTMLElement>('.LemonTable__toggle button')
            expect(button).not.toBeNull()
            return button as HTMLElement
        })
        await userEvent.click(toggle)
    },
}

// No repository in the digest and nothing posted yet, so the section reads as paused.
export const DigestsListEmpty: StoryObj = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/code_review/approvals/digests/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
                '/api/projects/:team_id/code_review/approvals/repositories/': {
                    ...repositories,
                    results: repositories.results.map((repo) => ({ ...repo, digest_enabled: false })),
                },
            },
        }),
    ],
}
