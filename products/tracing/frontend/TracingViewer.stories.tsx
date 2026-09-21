import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { makeSpan } from './__mocks__/span'
import { TracingViewer } from './TracingViewer'

const spans = [
    makeSpan({ uuid: 'root', name: 'GET /checkout', duration_nano: 250_000_000 }),
    makeSpan({
        uuid: 'child',
        span_id: 'span-2',
        parent_span_id: 'span-1',
        name: 'SELECT inventory',
        service_name: 'inventory',
        duration_nano: 100_000_000,
        is_root_span: false,
    }),
]

const meta: Meta<typeof TracingViewer> = {
    title: 'Products/Tracing/TracingViewer',
    component: TracingViewer,
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/tracing/spans/service-names': () => [
                    200,
                    { results: [{ name: 'checkout-api' }, { name: 'inventory' }] },
                ],
            },
            post: {
                '/api/environments/:team_id/tracing/spans/query': () => [200, { results: spans, hasMore: false }],
                '/api/environments/:team_id/tracing/spans/trace/:trace_id': () => [
                    200,
                    { results: spans, hasMore: false },
                ],
                '/api/environments/:team_id/tracing/spans/sparkline': () => [200, { results: [] }],
                '/api/environments/:team_id/tracing/spans/count': () => [200, { count: 2, traceCount: 1 }],
                '/api/environments/:team_id/tracing/spans/aggregate': () => [200, { results: [], compare: null }],
                '/api/environments/:team_id/tracing/spans/duration-histogram': () => [200, { results: [] }],
            },
        }),
        (Story) => (
            <div className="flex flex-col h-[700px] w-full">
                <Story />
            </div>
        ),
    ],
    parameters: {
        layout: 'fullscreen',
        mockDate: '2026-09-03T10:30:00Z',
        featureFlags: [FEATURE_FLAGS.TRACING_OPERATIONS_VIEW],
        testOptions: { viewportWidths: ['narrow', 'wide'] },
    },
    args: { id: 'embedded-tracing' },
}

export default meta
type Story = StoryObj<typeof TracingViewer>

export const Default: Story = {}

export const IndependentViewers: Story = {
    render: () => (
        <div className="flex flex-col gap-4 h-full">
            <div className="flex flex-col flex-1 min-h-0">
                <TracingViewer id="first-viewer" />
            </div>
            <div className="flex flex-col flex-1 min-h-0">
                <TracingViewer id="second-viewer" />
            </div>
        </div>
    ),
}
