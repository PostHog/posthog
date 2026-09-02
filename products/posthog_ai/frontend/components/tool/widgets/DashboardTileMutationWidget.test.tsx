import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { DashboardTileMutationWidget } from './DashboardTileMutationWidget'

function makeMessage(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey: 'dashboard-widgets-batch-add',
        rawServerName: 'posthog',
        rawToolName: 'mcp__posthog__exec',
        rawInput: {},
        innerInput: { id: 5 },
        rawOutput: { tiles: [{ id: 101 }] },
        content: [],
        status: 'completed',
        ...overrides,
    }
}

describe('DashboardTileMutationWidget', () => {
    afterEach(cleanup)

    it('reveals one changed tile on its dashboard', () => {
        render(<DashboardTileMutationWidget message={makeMessage()} isLastInGroup />)

        expect(screen.getByText('Show on dashboard').closest('a')).toHaveAttribute(
            'href',
            '/dashboard/5?highlightTileId=101'
        )
    })

    it('uses View dashboard when several tiles changed', () => {
        render(
            <DashboardTileMutationWidget
                message={makeMessage({ rawOutput: { tiles: [{ id: 101 }, { id: 102 }] } })}
                isLastInGroup
            />
        )

        expect(screen.getByText('View dashboard').closest('a')).toHaveAttribute('href', '/dashboard/5')
    })

    it('falls back to the generic card for malformed output', () => {
        render(
            <DashboardTileMutationWidget
                message={makeMessage({ rawOutput: undefined, innerToolName: 'dashboard-widgets-batch-add' })}
                isLastInGroup
            />
        )

        expect(screen.getByText('Call dashboard-widgets-batch-add')).toBeInTheDocument()
    })
})
