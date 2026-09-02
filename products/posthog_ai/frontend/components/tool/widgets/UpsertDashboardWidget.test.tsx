import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { UpsertDashboardWidget } from './UpsertDashboardWidget'

function makeMessage(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
    const innerInput = overrides.innerInput ?? { id: 5 }
    const rawOutput =
        overrides.rawOutput ??
        JSON.stringify({ id: 5, name: 'KPIs', _posthogUrl: 'https://us.posthog.com/project/1/dashboard/5' })
    const { innerInput: _innerInput, rawOutput: _rawOutput, ...messageOverrides } = overrides
    return {
        id: 'call-1',
        resolvedKey: 'dashboard-update',
        rawServerName: 'posthog',
        rawToolName: 'mcp__posthog__exec',
        rawInput: { command: `call --json dashboard-update ${JSON.stringify(innerInput)}` },
        innerToolName: 'dashboard-update',
        innerInput,
        rawOutput,
        content: [],
        status: 'completed',
        ...messageOverrides,
    }
}

describe('UpsertDashboardWidget', () => {
    afterEach(cleanup)

    it('reveals exactly one updated dashboard tile in the current tab', () => {
        render(
            <UpsertDashboardWidget
                message={makeMessage({ innerInput: { id: 5, tiles: [{ id: 101 }] } })}
                isLastInGroup
            />
        )

        expect(screen.getByText('Show on dashboard').closest('a')).toHaveAttribute(
            'href',
            '/dashboard/5?highlightTileId=101'
        )
        expect(screen.getByText('Show on dashboard').closest('a')).not.toHaveAttribute('target', '_blank')
    })

    it.each([
        ['a metadata-only update', { id: 5 }],
        ['a multi-tile update', { id: 5, tiles: [{ id: 101 }, { id: 102 }] }],
    ])('keeps View dashboard for %s', (_name, innerInput) => {
        render(<UpsertDashboardWidget message={makeMessage({ innerInput })} isLastInGroup />)

        expect(screen.getByText('View dashboard').closest('a')).toHaveAttribute(
            'href',
            'https://us.posthog.com/project/1/dashboard/5'
        )
        expect(screen.getByText('View dashboard').closest('a')).toHaveAttribute('target', '_blank')
    })

    it('uses the generic card when a completed dashboard update lacks its response ID', () => {
        render(
            <UpsertDashboardWidget
                message={makeMessage({ rawOutput: JSON.stringify({ name: 'KPIs' }) })}
                isLastInGroup
            />
        )

        expect(screen.getByText('Call dashboard-update')).toBeInTheDocument()
    })
})
