import type { Meta, StoryObj } from '@storybook/react'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { ObservationDockCard } from './ObservationCard'

const PROMPT = [
    'Did the user struggle to complete checkout?',
    '',
    'Answer yes if the user retried the payment form, went back to an earlier step, or left the page within a',
    'minute of seeing an error message. Answer no if the order went through without going back.',
].join('\n')

const observation = (overrides: Partial<ReplayObservationApi> = {}): ReplayObservationApi =>
    ({
        id: '00000000-0000-0000-0000-0000000000e1',
        scanner_id: '00000000-0000-0000-0000-00000000000a',
        scanner_origin: 'configured',
        session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d07',
        status: 'succeeded',
        error_reason: '',
        workflow_id: 'vision-observation-1',
        scanner_snapshot: {
            name: 'Confused checkout',
            scanner_type: 'monitor',
            scanner_version: 3,
            model: 'gemini-3.8-flash',
            provider: 'google',
            emits_signals: true,
            scanner_config: { prompt: PROMPT },
        },
        scanner_result: {
            model_output: {
                scanner_type: 'monitor',
                confidence: 0.82,
                verdict: 'yes',
                reasoning:
                    'The user entered a coupon code three times, got a validation error each time, then submitted the payment form twice before leaving the page.',
            },
            signals_count: 1,
        },
        prompt_question: 'Did the user struggle to complete checkout?',
        triggered_by: 'schedule',
        triggered_by_user: null,
        distinct_id: 'user_2m1x9d',
        recording_subject_email: 'bob@example.com',
        previous_observation_id: null,
        next_observation_id: null,
        label: null,
        viewed: true,
        media: [],
        summary_line: '',
        started_at: '2026-05-11T09:00:00Z',
        completed_at: '2026-05-11T09:01:00Z',
        created_at: '2026-05-11T09:00:00Z',
        ...overrides,
    }) as ReplayObservationApi

const meta: Meta<typeof ObservationDockCard> = {
    title: 'Replay Vision/Observation dock card',
    component: ObservationDockCard,
    decorators: [
        (Story) => (
            // The dock sits under the player, so the card gets the player column's width.
            <div className="w-120">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof ObservationDockCard>

export const Monitor: Story = { args: { observation: observation() } }

// Scanned before the prompt changed, so the scanner's current question no longer describes it.
export const MonitorScannedWithAnOlderPrompt: Story = {
    args: { observation: observation({ id: '00000000-0000-0000-0000-0000000000e2', prompt_question: null }) },
}
