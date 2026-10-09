import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import type {
    PatchedReviewUserSettingsApi,
    ReviewUserSettingsApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import { expect } from 'storybook/test'

import { CodeReviewScene } from './CodeReviewScene'

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

const meta: Meta<typeof CodeReviewScene> = {
    component: CodeReviewScene,
    title: 'Scenes/Code review',
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.REVIEW_HOG],
    },
    decorators: [
        (Story): JSX.Element => (
            <div className="p-4">
                <Story />
            </div>
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
                    '/api/projects/:team_id/review_hog/reviews/': { results: [], has_more: false },
                    '/api/projects/:team_id/review_hog/reviews/perspective_stats/': {
                        report_count: 0,
                        perspectives: [],
                    },
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
        userLogic.actions.loadUser()
        await waitFor(() => expect(userLogic.values.user?.is_staff).toBe(false))
        const canvas = within(canvasElement)
        await expect(await canvas.findByText('Review a pull request')).toBeVisible()
        await expect(canvas.queryByLabelText('Review all your Inbox PRs')).not.toBeInTheDocument()
        await expect(canvas.queryByLabelText('Let Stamphog review your Inbox PRs')).not.toBeInTheDocument()
        await expect(canvas.queryByLabelText('Review all your PRs with the reviewhog label')).not.toBeInTheDocument()
        await expect(canvas.queryByLabelText('Review all your PRs in Flash mode')).not.toBeInTheDocument()
        await expect(canvas.getByLabelText('Resolve comments on your PRs')).toBeVisible()
        await expect(canvas.getByLabelText('Celebrate clean reviews')).toBeVisible()
    },
}

export const InternalFeatures: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.REVIEW_HOG, FEATURE_FLAGS.REVIEW_HOG_INTERNAL],
        savedSettings: { stamphog_connected: true },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByLabelText('Review all your Inbox PRs')).toBeVisible()
        await expect(canvas.getByLabelText('Let Stamphog review your Inbox PRs')).toBeVisible()
        await expect(canvas.getByLabelText('Review all your PRs in Flash mode')).toBeVisible()
    },
}

export const SavedInboxOptIns: Story = {
    parameters: { savedSettings: { review_inbox_prs: true, stamphog_review_inbox_prs: true } },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const inboxSwitch = await canvas.findByLabelText('Review all your Inbox PRs')
        const stamphogSwitch = canvas.getByLabelText('Let Stamphog review your Inbox PRs')
        await expect(inboxSwitch).toBeChecked()
        await expect(inboxSwitch).toBeEnabled()
        await expect(stamphogSwitch).toBeChecked()
        await expect(stamphogSwitch).toBeEnabled()
        await expect(canvas.queryByLabelText('Review all your PRs with the reviewhog label')).not.toBeInTheDocument()
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

export const Narrow: Story = {
    decorators: [
        (Story): JSX.Element => (
            <div className="max-w-130">
                <Story />
            </div>
        ),
    ],
}
