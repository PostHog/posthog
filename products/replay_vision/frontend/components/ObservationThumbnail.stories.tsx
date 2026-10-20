import { Meta, StoryFn } from '@storybook/react'

import { IconPlayFilled } from '@posthog/icons'

import { mswDecorator } from '~/mocks/browser'
import { sessionFrameResponse } from '~/mocks/fixtures/sessionFrame'

import { ReplayObservationApi } from '../generated/api.schemas'
import { ObservationThumbnail } from './ObservationThumbnail'

const withFrame = {
    id: '0198f2a1-0000-7000-8000-000000000001',
    media: [{ id: '0198f2a1-0000-7000-8000-0000000000f1', kind: 'thumbnail', asset_id: 4001 }],
} as unknown as ReplayObservationApi

const withoutFrame = { id: '0198f2a1-0000-7000-8000-000000000002', media: [] } as unknown as ReplayObservationApi

const meta: Meta<typeof ObservationThumbnail> = {
    title: 'Scenes-App/Replay Vision/ObservationThumbnail',
    component: ObservationThumbnail,
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/vision/observations/:id/thumbnail/': () => sessionFrameResponse() },
        }),
    ],
}
export default meta

export const Frame: StoryFn = () => <ObservationThumbnail observation={withFrame} className="w-80" />

export const FrameAsAPlayTarget: StoryFn = () => (
    <ObservationThumbnail observation={withFrame} className="w-80">
        <IconPlayFilled className="text-xl text-brand-red drop-shadow" />
    </ObservationThumbnail>
)

// What an observation scanned before this shipped looks like, until a backfill gives it a frame.
export const NoFrameYet: StoryFn = () => <ObservationThumbnail observation={withoutFrame} className="w-80" />

export const FrameFailsToLoad: StoryFn = () => <ObservationThumbnail observation={withFrame} className="w-80" />
FrameFailsToLoad.decorators = [
    mswDecorator({
        get: { '/api/projects/:team_id/vision/observations/:id/thumbnail/': () => [500, {}] },
    }),
]
