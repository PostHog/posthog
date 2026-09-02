import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { UpsertDashboardWidget } from './UpsertDashboardWidget'

function makeMessage(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey: 'dashboard-update',
        rawServerName: 'posthog',
        rawToolName: 'mcp__posthog__exec',
        rawInput: {},
        innerInput: { id: 5 },
        rawOutput: { id: 5, name: 'KPIs' },
        content: [],
        status: 'completed',
        ...overrides,
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

        expect(screen.getByText('View dashboard').closest('a')).toHaveAttribute('href', '/dashboard/5')
        expect(screen.getByText('View dashboard').closest('a')).toHaveAttribute('target', '_blank')
    })
})
