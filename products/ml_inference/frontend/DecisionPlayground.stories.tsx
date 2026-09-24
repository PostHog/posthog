import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const answered = mswDecorator({
    post: {
        'api/projects/:team_id/ml_inference/decisions/decide/': [
            200,
            {
                model: 'kev-4b',
                answers: {
                    acceptable: {
                        type: 'noul',
                        probability: 0.31,
                        choice: null,
                        score: null,
                        confidence: null,
                        probabilities: null,
                    },
                    company_type: {
                        type: 'choice',
                        probability: null,
                        choice: 'saas',
                        score: null,
                        confidence: 0.91,
                        probabilities: { saas: 0.94, restaurant: 0.05, zoo: 0.01 },
                    },
                    importance: {
                        type: 'score',
                        probability: null,
                        choice: null,
                        score: 2.4,
                        confidence: 0.62,
                        probabilities: { '0': 0.02, '1': 0.08, '2': 0.38, '3': 0.52 },
                    },
                },
                input_tokens: 50,
                latency_ms: 31,
            },
        ],
    },
})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/MlInference',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-22',
        pageUrl: urls.decisionPlayground(),
        featureFlags: [FEATURE_FLAGS.ML_INFERENCE_DECISIONS],
    },
    decorators: [answered],
}
export default meta

type Story = StoryObj<{}>

// The playground before anything is asked: the example text and the three example questions.
export const Playground: Story = {}
