import { Meta, StoryFn } from '@storybook/react'

import { IconPlayFilled } from '@posthog/icons'

import { ReplayObservationApi } from '../generated/api.schemas'
import { ObservationThumbnail } from './ObservationThumbnail'

const observation = {
    id: '0198f2a1-0000-7000-8000-000000000001',
    session_id: '0198f2a1-1111-7000-8000-000000000002',
    media: [],
} as unknown as ReplayObservationApi

const meta: Meta<typeof ObservationThumbnail> = {
    title: 'Scenes-App/Replay Vision/ObservationThumbnail',
    component: ObservationThumbnail,
}
export default meta

// The rendered frame needs a signed export URL, so these cover the states a reader sees without one.
export const NoFrameYet: StoryFn = () => <ObservationThumbnail observation={observation} className="w-40" />

export const AsAPlayTarget: StoryFn = () => (
    <ObservationThumbnail observation={observation} className="w-40">
        <IconPlayFilled className="text-xl text-brand-red drop-shadow" />
    </ObservationThumbnail>
)
