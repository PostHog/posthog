import { Meta, StoryFn } from '@storybook/react'
import { waitFor } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect } from 'storybook/test'

import { makeSpan } from './__mocks__/span'

const SPANS = Array.from({ length: 30 }, (_, index) =>
    makeSpan({
        uuid: `span-${index}`,
        trace_id: `trace-${index}`,
        span_id: `span-${index}`,
        timestamp: `2023-02-17T23:${String(59 - index).padStart(2, '0')}:00Z`,
        end_time: `2023-02-17T23:${String(59 - index).padStart(2, '0')}:01Z`,
    })
)

const SPARKLINE = Array.from({ length: 12 }, (_, index) => ({
    time: `2023-02-17T23:${String(index * 5).padStart(2, '0')}:00Z`,
    service: 'checkout-api',
    count: 10 + index,
}))

export default {
    title: 'Scenes-App/Tracing',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tracing/spans/has_spans': () => [200, { hasSpans: true }],
                '/api/projects/:team_id/tracing/spans/attributes': () => [200, { results: [], count: 0 }],
                '/api/projects/:team_id/tracing_config': () => [
                    200,
                    {
                        tracing_distinct_id_attribute_keys: ['posthogDistinctId'],
                        tracing_session_id_attribute_keys: ['sessionId'],
                    },
                ],
                '/api/projects/:team_id/tracing/spans/service-names': () => [
                    200,
                    { results: [{ name: 'checkout-api' }] },
                ],
            },
            post: {
                '/api/projects/:team_id/tracing/spans/query': () => [200, { results: SPANS, hasMore: false }],
                '/api/projects/:team_id/tracing/spans/sparkline': () => [200, { results: SPARKLINE }],
                '/api/projects/:team_id/tracing/spans/count': () => [200, { count: 30, traceCount: 30 }],
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
        viewMode: 'story',
        mockDate: '2023-02-18',
        pageUrl: urls.tracing(),
        featureFlags: [FEATURE_FLAGS.TRACING_FACET_RAIL],
    },
} as Meta

// The list clips its rows, so a rendered row can still be out of sight. Check that one fits.
async function expectVisibleSpanRow({ canvasElement }: { canvasElement: HTMLElement }): Promise<void> {
    await waitFor(() => {
        const list = canvasElement.querySelector('[data-attr="tracing-spans-table"]')
        const row = list?.querySelector('[data-row-key]')
        expect(row).toBeTruthy()
        expect(row!.getBoundingClientRect().bottom).toBeLessThanOrEqual(list!.getBoundingClientRect().bottom)
    })
}

// The facet rail stacks above the results here.
export const TracingSceneNarrowShort: StoryFn = () => <App />
TracingSceneNarrowShort.parameters = {
    testOptions: {
        viewport: { width: 700, height: 600 },
        snapshotBrowsers: [],
    },
}
TracingSceneNarrowShort.play = expectVisibleSpanRow

// The facet rail sits beside the results, and the chart and filters take most of the height.
export const TracingSceneWideShort: StoryFn = () => <App />
TracingSceneWideShort.parameters = {
    testOptions: {
        viewport: { width: 1280, height: 420 },
        snapshotBrowsers: [],
    },
}
TracingSceneWideShort.play = expectVisibleSpanRow
