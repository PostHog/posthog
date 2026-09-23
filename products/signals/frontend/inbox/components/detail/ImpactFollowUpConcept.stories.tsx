import type { Meta, StoryObj } from '@storybook/react'

import { impactFollowUpExamples } from '../../__mocks__/impactFollowUpConceptMocks'
import type { FollowUpStage } from '../../__mocks__/impactFollowUpConceptMocks'
import { ImpactFollowUpConcept } from './ImpactFollowUpConcept'
import type { ImpactFollowUpConceptProps } from './ImpactFollowUpConcept'

const meta: Meta = {
    title: 'Scenes-App/Inbox/Impact follow-up concepts',
    parameters: { layout: 'fullscreen', viewMode: 'story' },
}
export default meta

type Story = StoryObj

export const AtAGlance: Story = {
    render: () => (
        <div className="min-h-screen bg-primary p-6">
            <div className="mx-auto flex max-w-5xl flex-col gap-5">
                <div>
                    <h1 className="mb-1 text-xl font-semibold">Impact at a glance</h1>
                    <p className="m-0 text-sm text-secondary">Early signs and final results · five illustrative reports · invented data</p>
                </div>
                {impactFollowUpExamples.map((example, index) => (
                    <ImpactFollowUpConcept key={example.id} example={example} stage={index < 2 ? 'finished' : 'watching'} version="inbox" />
                ))}
            </div>
        </div>
    ),
}

function gallery(stage: FollowUpStage, version: ImpactFollowUpConceptProps['version']): JSX.Element {
    const names = { beacon: 'A · The beacon', scoreboard: 'B · The scoreboard', inbox: 'C · The inbox strip', two_signals: 'D · Change + proof' }
    return (
        <div className="min-h-screen bg-primary p-6">
            <div className="mx-auto flex max-w-5xl flex-col gap-8">
                <div>
                    <h1 className="mb-1 text-xl font-semibold">
                        {names[version]} ·{' '}
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

export const BeaconBeforeMerge: Story = { render: () => gallery('planned', 'beacon') }
export const BeaconWatching: Story = { render: () => gallery('watching', 'beacon') }
export const BeaconAfterWindow: Story = { render: () => gallery('finished', 'beacon') }

export const ScoreboardBeforeMerge: Story = { render: () => gallery('planned', 'scoreboard') }
export const ScoreboardWatching: Story = { render: () => gallery('watching', 'scoreboard') }
export const ScoreboardAfterWindow: Story = { render: () => gallery('finished', 'scoreboard') }

export const InboxBeforeMerge: Story = { render: () => gallery('planned', 'inbox') }
export const InboxWatching: Story = { render: () => gallery('watching', 'inbox') }
export const InboxAfterWindow: Story = { render: () => gallery('finished', 'inbox') }

export const ChangeAndProofBeforeMerge: Story = { render: () => gallery('planned', 'two_signals') }
export const ChangeAndProofWatching: Story = { render: () => gallery('watching', 'two_signals') }
export const ChangeAndProofAfterWindow: Story = { render: () => gallery('finished', 'two_signals') }
