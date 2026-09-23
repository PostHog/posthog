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

function gallery(stage: FollowUpStage, version: ImpactFollowUpConceptProps['version']): JSX.Element {
    const names = {
        poster: '01 · Decision poster',
        queue: '02 · Inbox queue',
        tape: '03 · Daily tape',
        'poster-runway': '04 · Decision poster + runway',
    }
    return (
        <div className="min-h-screen bg-primary p-5">
            <div className={`mx-auto flex flex-col ${version === 'queue' ? 'max-w-7xl gap-2' : 'max-w-5xl gap-5'}`}>
                <div className="mb-3">
                    <h1 className="mb-1 text-xl font-semibold">
                        {names[version]} ·{' '}
                        {stage === 'planned'
                            ? 'Before release'
                            : stage === 'watching'
                              ? 'Watching'
                              : 'After the window'}
                    </h1>
                    <p className="m-0 text-sm text-secondary">
                        Five cases · invented data · controls are a preview only
                    </p>
                </div>
                {impactFollowUpExamples.map((example) => (
                    <ImpactFollowUpConcept key={example.id} example={example} stage={stage} version={version} />
                ))}
            </div>
        </div>
    )
}

export const AtAGlance: Story = {
    render: () => (
        <div className="min-h-screen bg-primary p-5">
            <div className="mx-auto flex max-w-7xl flex-col gap-2">
                <div className="mb-3">
                    <h1 className="mb-1 text-xl font-semibold">Impact at a glance · inbox queue</h1>
                    <p className="m-0 text-sm text-secondary">Early signs and final results · invented data</p>
                </div>
                {impactFollowUpExamples.map((example, index) => (
                    <ImpactFollowUpConcept
                        key={example.id}
                        example={example}
                        stage={index < 2 ? 'finished' : 'watching'}
                        version="queue"
                    />
                ))}
            </div>
        </div>
    ),
}

export const PosterBeforeRelease: Story = { render: () => gallery('planned', 'poster') }
export const PosterWatching: Story = { render: () => gallery('watching', 'poster') }
export const PosterAfterWindow: Story = { render: () => gallery('finished', 'poster') }

export const QueueBeforeRelease: Story = { render: () => gallery('planned', 'queue') }
export const QueueWatching: Story = { render: () => gallery('watching', 'queue') }
export const QueueAfterWindow: Story = { render: () => gallery('finished', 'queue') }

export const TapeBeforeRelease: Story = { render: () => gallery('planned', 'tape') }
export const TapeWatching: Story = { render: () => gallery('watching', 'tape') }
export const TapeAfterWindow: Story = { render: () => gallery('finished', 'tape') }

export const PosterRunwayBeforeRelease: Story = { render: () => gallery('planned', 'poster-runway') }
export const PosterRunwayWatching: Story = { render: () => gallery('watching', 'poster-runway') }
export const PosterRunwayAfterWindow: Story = { render: () => gallery('finished', 'poster-runway') }
