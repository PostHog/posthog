import { Meta, StoryFn } from '@storybook/react'

import type { ObservationSearchResultApi, ReplayObservationApi } from '../generated/api.schemas'
import { MomentCard, MomentRow } from './SearchResults'

// `media: []` renders the neutral frame, so the card needs no thumbnail request. Only the fields the
// card and its children read are set; the cast keeps the fixture to those.
const observation = (overrides: Partial<ReplayObservationApi> = {}): ReplayObservationApi =>
    ({
        id: '00000000-0000-0000-0000-0000000000b1',
        scanner_id: '00000000-0000-0000-0000-00000000000a',
        session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d07',
        status: 'succeeded',
        scanner_origin: 'configured',
        scanner_snapshot: {
            name: 'Confused checkout',
            scanner_type: 'monitor',
            scanner_config: { prompt: 'Did the user struggle at checkout?' },
        },
        scanner_result: {
            model_output: {
                scanner_type: 'monitor',
                verdict: 'yes',
                confidence: 0.82,
                reasoning: 'The user retried the coupon three times, then resubmitted payment before leaving.',
            },
        },
        distinct_id: 'user_2m1x9d',
        recording_subject_email: 'bob@example.com',
        created_at: '2026-08-12T09:00:00Z',
        media: [],
        ...overrides,
    }) as unknown as ReplayObservationApi

const result: ObservationSearchResultApi = {
    observation: observation(),
    distance: 0.12,
    matched_content: 'The user retried the coupon code three times and gave up at checkout.',
}

const meta: Meta<typeof MomentCard> = {
    title: 'Scenes-App/Replay Vision/Search results',
    component: MomentCard,
}
export default meta

// A grid result whose recording retention deleted the recording: the expired tag replaces the play
// affordance, and the analysis stays readable.
export const ExpiredGridCard: StoryFn = () => (
    <div className="w-80">
        <MomentCard result={result} searchedQuery="gave up" returnParams={{}} expired={true} tier={null} />
    </div>
)

// The same card while the recording still plays, for contrast: the poster keeps its play target.
export const PlayableGridCard: StoryFn = () => (
    <div className="w-80">
        <MomentCard result={result} searchedQuery="gave up" returnParams={{}} expired={false} tier={null} />
    </div>
)

// The list layout carries the expired tag inline in the header row.
export const ExpiredListRow: StoryFn = () => (
    <div className="w-[42rem]">
        <MomentRow result={result} searchedQuery="gave up" returnParams={{}} expired={true} />
    </div>
)
