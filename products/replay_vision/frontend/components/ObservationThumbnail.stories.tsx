import { Meta, StoryFn } from '@storybook/react'

import { IconPlayFilled } from '@posthog/icons'

import { ObservationThumbnail } from './ObservationThumbnail'

const observationId = '0198f2a1-0000-7000-8000-000000000001'

const meta: Meta<typeof ObservationThumbnail> = {
    title: 'Scenes-App/Replay Vision/ObservationThumbnail',
    component: ObservationThumbnail,
}
export default meta

// The rendered frame needs a signed export URL, so these cover the states a reader sees without one.
export const NoFrameYet: StoryFn = () => <ObservationThumbnail observationId={observationId} className="w-40" />

export const AsAPlayTarget: StoryFn = () => (
    <ObservationThumbnail observationId={observationId} className="w-40">
        <IconPlayFilled className="text-xl text-brand-red drop-shadow" />
    </ObservationThumbnail>
)
