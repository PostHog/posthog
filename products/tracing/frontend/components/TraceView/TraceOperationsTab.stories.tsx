import { Meta, StoryObj } from '@storybook/react'

import type { Span } from '../../types'
import { TraceOperationsTab } from './TraceOperationsTab'

const T0 = Date.UTC(2026, 8, 3, 10, 0, 0)

function span(
    span_id: string,
    parent_span_id: string,
    service_name: string,
    name: string,
    startMs: number,
    durationMs: number
): Span {
    return {
        uuid: span_id,
        trace_id: '0f3b7c1a5e2d48960b7a1c3e5d9f2048',
        span_id,
        parent_span_id,
        name,
        kind: parent_span_id ? 3 : 2,
        service_name,
        status_code: 1,
        timestamp: new Date(T0 + startMs).toISOString(),
        end_time: new Date(T0 + startMs + durationMs).toISOString(),
        duration_nano: durationMs * 1_000_000,
        is_root_span: !parent_span_id,
        matched_filter: true,
        attributes: {},
        resource_attributes: {},
    }
}

// A 3.8 s checkout trace. The first SELECT holds three of the cache reads, so "This span" has a subtree.
const ROOT = span('root', '', 'checkout-api', 'POST /api/orders', 0, 3800)
const SELECTS = Array.from({ length: 22 }, (_, i) =>
    span(`select-${i}`, 'root', 'postgres', 'SELECT orders', 2 + i * 2, 18 + (i % 5) * 2)
)
const CACHE_GETS = Array.from({ length: 1751 }, (_, i) =>
    i < 3
        ? span(`cache-${i}`, 'select-0', 'checkout-api', 'cache GET', 3 + i * 2, 0.6)
        : span(`cache-${i}`, 'root', 'checkout-api', 'cache GET', 120 + i * 2, 0.4 + (i % 7) * 0.1)
)
const RESERVES = Array.from({ length: 4 }, (_, i) =>
    span(`reserve-${i}`, 'root', 'inventory', 'reserveStock', 400 + i * 700, 52)
)
const EMAIL = span('email', 'root', 'notifications', 'enqueueEmail', 3700, 12)
const SPANS: Span[] = [ROOT, ...SELECTS, ...CACHE_GETS, ...RESERVES, EMAIL]

const meta: Meta<typeof TraceOperationsTab> = {
    title: 'Products/Tracing/TraceOperationsTab',
    component: TraceOperationsTab,
    tags: ['autodocs'],
    args: {
        span: ROOT,
        spans: SPANS,
        highlightedOperationKey: null,
        onHighlightOperation: () => {},
        partial: false,
    },
    // The table measures its container, so the story fixes the width of the inspector in a 1280px window.
    decorators: [
        (Story) => (
            <div className="w-[420px]">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof TraceOperationsTab>

export const WholeTrace: Story = {}

/** The inspector at its narrowest, 320px less its 16px left padding. Share stays in view, and long names truncate. */
export const Narrowest: Story = {
    decorators: [
        (Story) => (
            <div className="w-[304px]">
                <Story />
            </div>
        ),
    ],
}

/** One SELECT and the cache reads under it. */
export const ThisSpan: Story = {
    args: { span: SELECTS[0] },
    play: async ({ canvas, userEvent }): Promise<void> => {
        await userEvent.click(await canvas.findByText('This span'))
        // The synthetic click leaves a focus ring that a person's click does not show.
        ;(document.activeElement as HTMLElement | null)?.blur()
    },
}
