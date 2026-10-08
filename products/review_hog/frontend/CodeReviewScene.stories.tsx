import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Decorator, Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import type {
    PatchedReviewUserSettingsApi,
    ReviewPerspectiveStatsApi,
    ReviewRecentReviewApi,
    ReviewUserSettingsApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import { expect } from 'storybook/test'

import { CodeReviewScene } from './CodeReviewScene'
import { CodeReviewTab } from './reviewHogSettingsLogic'

const defaultSettings: ReviewUserSettingsApi = {
    default_review_mode: 'follow',
    resolve_comments: false,
    urgency_threshold: 'consider',
    celebrate_clean_reviews: true,
    review_inbox_prs: false,
    stamphog_review_inbox_prs: false,
    sources: {
        default_review_mode: 'default',
        resolve_comments: 'default',
        urgency_threshold: 'default',
        celebrate_clean_reviews: 'default',
        review_inbox_prs: 'default',
        stamphog_review_inbox_prs: 'default',
    },
    project_defaults: { urgency_threshold: 'consider', celebrate_clean_reviews: true },
    stamphog_connected: false,
}

function completedReview(overrides: Partial<ReviewRecentReviewApi>): ReviewRecentReviewApi {
    return {
        id: 'review-1',
        repository: 'example-org/example-repo',
        pr_number: 101,
        pr_title: 'Add retry to the export job',
        pr_author: 'example-dev',
        additions: 120,
        deletions: 34,
        changed_files: 6,
        head_branch: 'feat/export-retry',
        github_url: 'https://github.com/example-org/example-repo/pull/101',
        run_count: 1,
        last_run_at: '2026-09-30T10:00:00Z',
        published: true,
        in_progress: false,
        progress: null,
        resolution: null,
        must_fix_count: 1,
        should_fix_count: 2,
        consider_count: 1,
        candidate_count: 7,
        dismissed_count: 3,
        files_reviewed: 6,
        chunk_count: 2,
        perspective_count: 3,
        perspective_issue_count: 8,
        blind_spot_issue_count: 2,
        ...overrides,
    }
}

const recentReviews: ReviewRecentReviewApi[] = [
    completedReview({}),
    completedReview({
        id: 'review-2',
        pr_number: 98,
        pr_title: 'Fix timezone handling in the weekly digest',
        github_url: 'https://github.com/example-org/example-repo/pull/98',
        head_branch: 'fix/digest-timezone',
        last_run_at: '2026-09-29T15:30:00Z',
        must_fix_count: 0,
        should_fix_count: 1,
        consider_count: 0,
        dismissed_count: 1,
    }),
]

const perspectiveStats: ReviewPerspectiveStatsApi = {
    report_count: 2,
    perspectives: [
        { skill_name: 'review-hog-perspective-logic-correctness', raised: 6, kept: 4, dismissed: 2 },
        { skill_name: 'review-hog-perspective-performance-reliability', raised: 3, kept: 1, dismissed: 2 },
        { skill_name: 'review-hog-blind-spots-general', raised: 2, kept: 1, dismissed: 1 },
    ],
}

function OpenTab({ tab, children }: { tab: CodeReviewTab; children: JSX.Element }): JSX.Element {
    useEffect(() => {
        router.actions.replace(urls.codeReview(), tab === 'settings' ? { tab } : {})
    }, [tab])
    return children
}

const meta: Meta<typeof CodeReviewScene> = {
    component: CodeReviewScene,
    title: 'Scenes/Code review',
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.REVIEW_HOG],
        mockDate: '2026-10-01T12:00:00Z',
    },
    decorators: [
        (Story, context): JSX.Element => (
            <OpenTab tab={context.parameters.tab ?? 'activity'}>
                <div className="p-4">
                    <Story />
                </div>
            </OpenTab>
        ),
        (Story, context): JSX.Element => {
            let settings: ReviewUserSettingsApi = {
                ...defaultSettings,
                ...context.parameters.savedSettings,
            }
            return mswDecorator({
                get: {
                    '/api/users/@me/': () => [
                        200,
                        { ...MOCK_DEFAULT_USER, is_staff: context.parameters.isStaff ?? false },
                    ],
                    '/api/projects/:team_id/review_hog/settings/': () => [200, settings],
                    '/api/projects/:team_id/review_hog/reviews/': { results: recentReviews, has_more: false },
                    '/api/projects/:team_id/review_hog/reviews/perspective_stats/': perspectiveStats,
                    '/api/projects/:team_id/review_hog/perspectives/': [],
                    '/api/projects/:team_id/review_hog/blind_spots/': [],
                    '/api/projects/:team_id/review_hog/validators/': [],
                    '/api/projects/:team_id/review_hog/resolution/': [],
                },
                patch: {
                    '/api/projects/:team_id/review_hog/settings/': async ({ request }) => {
                        const update = (await request.json()) as PatchedReviewUserSettingsApi
                        settings = { ...settings, ...update }
                        return [200, settings]
                    },
                },
            })(Story, context)
        },
    ],
}
export default meta

type Story = StoryObj<typeof CodeReviewScene>

export const Default: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByText('Review a pull request')).toBeVisible()
        await expect(await canvas.findByText('Add retry to the export job')).toBeVisible()
        await expect(canvas.getByText('Mine')).toBeVisible()
        await expect(canvas.queryByLabelText('Celebrate clean reviews')).not.toBeInTheDocument()
    },
}

export const Settings: Story = {
    parameters: { tab: 'settings' },
    play: async ({ canvasElement }) => {
        userLogic.actions.loadUser()
        await waitFor(() => expect(userLogic.values.user?.is_staff).toBe(false))
        const canvas = within(canvasElement)
        await expect(await canvas.findByText('What gets reviewed')).toBeVisible()
        await expect(canvas.queryByText('Review a pull request')).not.toBeInTheDocument()
        await expect(canvas.queryByLabelText('Review all your Inbox PRs')).not.toBeInTheDocument()
        await expect(canvas.queryByLabelText('Let Stamphog review your Inbox PRs')).not.toBeInTheDocument()
        await expect(canvas.queryByLabelText('Review all your PRs in Flash mode')).not.toBeInTheDocument()
        await expect(canvas.getByLabelText('Resolve comments on your PRs')).toBeVisible()
        await expect(canvas.getByLabelText('Celebrate clean reviews')).toBeVisible()
    },
}

export const InternalFeatures: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.REVIEW_HOG, FEATURE_FLAGS.REVIEW_HOG_INTERNAL],
        savedSettings: { stamphog_connected: true },
    tab: 'settings',
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByLabelText('Review all your Inbox PRs')).toBeVisible()
        await expect(canvas.getByLabelText('Let Stamphog review your Inbox PRs')).toBeVisible()
        await expect(canvas.getByLabelText('Review all your PRs in Flash mode')).toBeVisible()
    },
}

export const SavedInboxOptIns: Story = {
    parameters: { savedSettings: { review_inbox_prs: true, stamphog_review_inbox_prs: true }, tab: 'settings' },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const inboxSwitch = await canvas.findByLabelText('Review all your Inbox PRs')
        const stamphogSwitch = canvas.getByLabelText('Let Stamphog review your Inbox PRs')
        await expect(inboxSwitch).toBeChecked()
        await expect(inboxSwitch).toBeEnabled()
        await expect(stamphogSwitch).toBeChecked()
        await expect(stamphogSwitch).toBeEnabled()
        await expect(canvas.queryByLabelText('Review all your PRs in Flash mode')).not.toBeInTheDocument()
    },
}

export const FlagDisabledForStaff: Story = {
    parameters: { featureFlags: [], isStaff: true },
    play: async ({ canvasElement }) => {
        userLogic.actions.loadUser()
        await waitFor(() => expect(userLogic.values.user?.is_staff).toBe(true))
        const canvas = within(canvasElement)
        await expect(await canvas.findByText('Page not found')).toBeVisible()
        await expect(canvas.queryByText('Review a pull request')).not.toBeInTheDocument()
    },
}

const narrowDecorator: Decorator = (Story): JSX.Element => (
    <div className="max-w-130">
        <Story />
    </div>
)

export const Narrow: Story = {
    decorators: [narrowDecorator],
}

export const NarrowSettings: Story = {
    parameters: { tab: 'settings' },
    decorators: [narrowDecorator],
}
