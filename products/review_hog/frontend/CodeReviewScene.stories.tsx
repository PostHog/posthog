import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type {
    PatchedReviewUserSettingsApi,
    ReviewUserSettingsApi,
} from 'products/review_hog/frontend/generated/api.schemas'

import { CodeReviewScene } from './CodeReviewScene'

const defaultSettings: ReviewUserSettingsApi = {
    review_inbox_prs: false,
    stamphog_review_inbox_prs: false,
    review_labeled_prs: true,
    resolve_comments: true,
    review_authored_prs: false,
    flash_reasoning_effort: 'medium',
    urgency_threshold: 'consider',
    can_trigger_reviews: true,
    stamphog_connected: true,
}

const meta: Meta<typeof CodeReviewScene> = {
    component: CodeReviewScene,
    title: 'Scenes/Code review',
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.REVIEW_HOG],
    },
    decorators: [
        (Story, context): JSX.Element => {
            let settings = { ...defaultSettings }
            return mswDecorator({
                get: {
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

export const Default: Story = {}

export const Narrow: Story = {
    decorators: [
        (Story): JSX.Element => (
            <div className="max-w-130">
                <Story />
            </div>
        ),
    ],
}
