import type { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type { AEOCompetitorCandidateApi } from '../generated/api.schemas'
import { AiVisibilityCompetitorReview } from './AiVisibilityCompetitorReview'

const candidate = (id: number, name: string, naming: number, citing: number): AEOCompetitorCandidateApi => ({
    brand_id: `00000000-0000-4000-8000-${String(900 + id).padStart(12, '0')}`,
    name,
    domain: `${name.toLowerCase().replace(/ /g, '')}.example.org`,
    answers_naming: naming,
    answers_citing: citing,
})

const CANDIDATES: AEOCompetitorCandidateApi[] = [
    candidate(1, 'Rival', 412, 268),
    candidate(2, 'Flagship', 301, 144),
    candidate(3, 'Open Metrics', 187, 131),
    candidate(4, 'Forum', 96, 240),
    candidate(5, 'Charts Co', 88, 61),
    candidate(6, 'Tracker', 42, 37),
    candidate(7, 'Dev Weekly', 12, 95),
]

const meta: Meta<typeof AiVisibilityCompetitorReview> = {
    title: 'Products/Web Analytics/Content autopilot/Competitor review',
    component: AiVisibilityCompetitorReview,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/aeo_brands/competitor_candidates/': () => [200, CANDIDATES],
                '/api/projects/:team_id/aeo_brands/': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
            },
            patch: {
                '/api/projects/:team_id/aeo_brands/:id/': () => [200, {}],
            },
        }),
    ],
}

export default meta

export const Suggestions: StoryFn<typeof AiVisibilityCompetitorReview> = () => (
    <div className="p-4 max-w-200">
        <AiVisibilityCompetitorReview />
    </div>
)
