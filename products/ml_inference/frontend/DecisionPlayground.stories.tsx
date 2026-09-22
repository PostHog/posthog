import { Meta, StoryObj } from '@storybook/react'

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
                    urgent: {
                        type: 'noul',
                        probability: 0.94,
                        choice: null,
                        score: null,
                        confidence: null,
                        probabilities: null,
                    },
                    queue: {
                        type: 'choice',
                        probability: null,
                        choice: 'billing',
                        score: null,
                        confidence: 0.94,
                        probabilities: { billing: 0.97, support: 0.03 },
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
    },
    decorators: [answered],
}
export default meta

type Story = StoryObj<{}>

// The playground before anything is asked: the example ticket and two example questions.
export const Playground: Story = {}
