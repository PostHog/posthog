import { Meta, StoryObj } from '@storybook/react'

import { TraceAiEventsCapNotice } from './TraceAiEventsCapNotice'

const meta: Meta<typeof TraceAiEventsCapNotice> = {
    title: 'Products/Tracing/TraceAiEventsCapNotice',
    component: TraceAiEventsCapNotice,
    args: {
        hasMore: true,
        aiEvents: [
            {
                uuid: '0190a1b2-0000-7000-8000-000000000001',
                event: '$ai_generation',
                started_at: '2026-06-02T08:00:03.000Z',
                ai_trace_id: '4bf92f3577b34da6a3ce929d0e0e4736',
                ai_span_id: null,
                ai_parent_id: null,
                span_name: null,
                latency_seconds: 2,
                model: 'model-x',
                provider: 'provider-y',
                input_tokens: 10,
                output_tokens: 5,
                total_cost_usd: 0.01,
                is_error: false,
            },
        ],
    },
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof TraceAiEventsCapNotice>

export const PastTheCap: Story = {}
