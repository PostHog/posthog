import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { makeSpan } from '../../__mocks__/span'
import type { Span } from '../../types'
import { SpanSummaryHeader } from './SpanSummaryHeader'

jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }) => <span>{time}</span>,
}))

const AI_TRACE_ID = '4bf92f35-77b3-4da6-a3ce-929d0e0e4736'

describe('SpanSummaryHeader', () => {
    test.each<[string, Span, { href: string; target: string } | null]>([
        [
            'an AI row',
            makeSpan({ uuid: 'e1', span_id: 'ai:e1', attributes: { 'ai.trace_id': AI_TRACE_ID } }),
            { href: `/ai-observability/traces/${AI_TRACE_ID}?event=e1`, target: '_blank' },
        ],
        ['a real span', makeSpan(), null],
    ])('renders the AI observability link for %s', (_, span, expected) => {
        const { container } = render(<SpanSummaryHeader span={span} serviceColorMap={new Map()} />)
        const button = container.querySelector('[data-attr="tracing-ai-event-view-in-ai-observability"]')
        const link = button && { href: button.getAttribute('href'), target: button.getAttribute('target') }

        expect(link).toEqual(expected)
    })
})
