import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { CreateInsightWidget } from './CreateInsightWidget'

jest.mock('~/queries/Query/Query', () => ({ Query: () => <div>Visualization</div> }))

function makeMessage(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
    const innerInput = overrides.innerInput ?? { dashboards: [5] }
    const rawOutput =
        overrides.rawOutput ?? JSON.stringify({ short_id: 'abc123', query: { kind: 'TrendsQuery', series: [] } })
    const { innerInput: _innerInput, rawOutput: _rawOutput, ...messageOverrides } = overrides
    return {
        id: 'call-1',
        resolvedKey: 'insight-create',
        rawServerName: 'posthog',
        rawToolName: 'mcp__posthog__exec',
        rawInput: { command: `call --json insight-create ${JSON.stringify(innerInput)}` },
        innerToolName: 'insight-create',
        innerInput,
        rawOutput,
        content: [],
        status: 'completed',
        ...messageOverrides,
    }
}

describe('CreateInsightWidget', () => {
    afterEach(cleanup)

    it('adds a dashboard reveal action for an insight created on one dashboard', () => {
        render(<CreateInsightWidget message={makeMessage()} isLastInGroup />)

        expect(screen.getByText('Show on dashboard').closest('a')).toHaveAttribute(
            'href',
            '/dashboard/5?highlightInsightId=abc123'
        )
    })

    it('keeps the insight action without an ambiguous dashboard reveal', () => {
        render(<CreateInsightWidget message={makeMessage({ innerInput: { dashboards: [5, 6] } })} isLastInGroup />)

        expect(screen.queryByText('Show on dashboard')).not.toBeInTheDocument()
        expect(document.querySelector('a[href="/insights/abc123"]')).toBeInTheDocument()
    })

    it('uses the generic card when a completed insight record is schema-incomplete', () => {
        render(
            <CreateInsightWidget
                message={makeMessage({ rawOutput: JSON.stringify({ short_id: 'abc123' }) })}
                isLastInGroup
            />
        )

        expect(screen.getByText('Call insight-create')).toBeInTheDocument()
    })
})
