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

function gallery(stage: FollowUpStage, version: 'summary' | 'evidence'): JSX.Element {
    return (
        <div className="min-h-screen bg-primary p-6">
            <div className="mx-auto flex max-w-4xl flex-col gap-6">
                <div>
                    <h1 className="mb-1 text-xl font-semibold">
                        {version === 'summary' ? 'A · Summary first' : 'B · Evidence first'} ·{' '}
                        {stage === 'planned' ? 'Before merge' : stage === 'watching' ? 'Watching after merge' : 'After the window'}
                    </h1>
                    <p className="m-0 text-sm text-secondary">
                        Five illustrative reports · synthetic data · Storybook-only interactions
                    </p>
                </div>
                {impactFollowUpExamples.map((example) => (
                    <ImpactFollowUpConcept key={example.id} example={example} stage={stage} version={version} />
                ))}
            </div>
        </div>
    )
}

export const SummaryBeforeMerge: Story = { render: () => gallery('planned', 'summary') }
export const SummaryWatching: Story = { render: () => gallery('watching', 'summary') }
export const SummaryAfterWindow: Story = { render: () => gallery('finished', 'summary') }

export const EvidenceBeforeMerge: Story = { render: () => gallery('planned', 'evidence') }
export const EvidenceWatching: Story = { render: () => gallery('watching', 'evidence') }
export const EvidenceAfterWindow: Story = { render: () => gallery('finished', 'evidence') }
