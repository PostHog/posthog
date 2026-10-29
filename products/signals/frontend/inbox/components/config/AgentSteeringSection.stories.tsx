import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { SignalTeamConfigApi } from '../../../generated/api.schemas'
import { AgentSteeringSection } from './AgentSteeringSection'

const config = {
    scout_instructions: 'Focus on onboarding failures. Exclude demo accounts from impact estimates.',
    research_instructions: 'Confirm whether the behavior is intentional before proposing a fix.',
    implementation_instructions: 'Keep changes focused. Add regression coverage and open draft pull requests.',
}

const meta: Meta<typeof AgentSteeringSection> = {
    title: 'Scenes-App/Inbox/Agent steering',
    component: AgentSteeringSection,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/config/': config,
            },
            post: {
                '/api/projects/:id/signals/config/': async ({ request }) => [
                    200,
                    { ...config, ...((await request.json()) as SignalTeamConfigApi) },
                ],
            },
        }),
        (Story) => (
            <div className="max-w-160">
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof AgentSteeringSection>

export const Configured: Story = {}

export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/config/': {
                    scout_instructions: '',
                    research_instructions: '',
                    implementation_instructions: '',
                },
            },
        }),
    ],
}
