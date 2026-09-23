import type { Meta, StoryObj } from '@storybook/react'

import { impactFollowUpExamples } from '../../__mocks__/impactFollowUpConceptMocks'
import type { FollowUpStage } from '../../__mocks__/impactFollowUpConceptMocks'
import { ImpactFollowUpConcept } from './ImpactFollowUpConcept'

const meta: Meta = {
    title: 'Scenes-App/Inbox/Impact follow-up concepts',
    parameters: { layout: 'fullscreen', viewMode: 'story' },
}
export default meta

type Story = StoryObj

function gallery(stage: FollowUpStage, version: 'trend' | 'countdown' | 'checkpoints'): JSX.Element {
    return (
        <div className="min-h-screen bg-primary p-6">
            <div className="mx-auto flex max-w-5xl flex-col gap-8">
                <div>
                    <h1 className="mb-1 text-xl font-semibold">
                        {version === 'trend' ? 'A · The trend' : version === 'countdown' ? 'B · The countdown' : 'C · The checkpoints'} ·{' '}
                        {stage === 'planned' ? 'Before merge' : stage === 'watching' ? 'Watching after merge' : 'After the window'}
                    </h1>
                    <p className="m-0 text-sm text-secondary">
                        Five illustrative reports · invented counts and dates · Storybook-only interactions
                    </p>
                </div>
                {impactFollowUpExamples.map((example) => (
                    <ImpactFollowUpConcept key={example.id} example={example} stage={stage} version={version} />
                ))}
            </div>
        </div>
    )
}

export const TrendBeforeMerge: Story = { render: () => gallery('planned', 'trend') }
export const TrendWatching: Story = { render: () => gallery('watching', 'trend') }
export const TrendAfterWindow: Story = { render: () => gallery('finished', 'trend') }

export const CountdownBeforeMerge: Story = { render: () => gallery('planned', 'countdown') }
export const CountdownWatching: Story = { render: () => gallery('watching', 'countdown') }
export const CountdownAfterWindow: Story = { render: () => gallery('finished', 'countdown') }

export const CheckpointsBeforeMerge: Story = { render: () => gallery('planned', 'checkpoints') }
export const CheckpointsWatching: Story = { render: () => gallery('watching', 'checkpoints') }
export const CheckpointsAfterWindow: Story = { render: () => gallery('finished', 'checkpoints') }
