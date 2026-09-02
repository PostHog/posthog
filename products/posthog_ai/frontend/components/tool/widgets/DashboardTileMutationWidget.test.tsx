import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { DashboardTileMutationWidget } from './DashboardTileMutationWidget'

function makeMessage(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
    const innerInput = overrides.innerInput ?? {
        id: 5,
        widgets: [{ widget_type: 'activity_events_list', config: {} }],
    }
    const rawOutput = overrides.rawOutput ?? JSON.stringify({ tiles: [{ id: 101 }] })
    const { innerInput: _innerInput, rawOutput: _rawOutput, ...messageOverrides } = overrides
    return {
        id: 'call-1',
        resolvedKey: 'dashboard-widgets-batch-add',
        rawServerName: 'posthog',
        rawToolName: 'mcp__posthog__exec',
        rawInput: { command: `call --json dashboard-widgets-batch-add ${JSON.stringify(innerInput)}` },
        innerToolName: 'dashboard-widgets-batch-add',
        innerInput,
        rawOutput,
        content: [],
        status: 'completed',
        ...messageOverrides,
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
                message={makeMessage({
                    innerInput: {
                        id: 5,
                        widgets: [
                            { widget_type: 'activity_events_list', config: {} },
                            { widget_type: 'logs_list', config: {} },
                        ],
                    },
                    rawOutput: JSON.stringify({ tiles: [{ id: 101 }, { id: 102 }] }),
                })}
                isLastInGroup
            />
        )

        expect(screen.getByText('View dashboard').closest('a')).toHaveAttribute('href', '/dashboard/5')
    })

    it('falls back to the generic card for a completed schema-incomplete record', () => {
        render(<DashboardTileMutationWidget message={makeMessage({ rawOutput: JSON.stringify({}) })} isLastInGroup />)

        expect(screen.getByText('Call dashboard-widgets-batch-add')).toBeInTheDocument()
    })

    it('falls back to the generic card when the successful batch shape contradicts its request', () => {
        render(
            <DashboardTileMutationWidget
                message={makeMessage({
                    resolvedKey: 'dashboard-widgets-batch-update',
                    innerToolName: 'dashboard-widgets-batch-update',
                    innerInput: { id: 5, widgets: [{ tile_id: 101 }] },
                    rawOutput: JSON.stringify({ tiles: [{ id: 102 }] }),
                })}
                isLastInGroup
            />
        )

        expect(screen.getByText('Call dashboard-widgets-batch-update')).toBeInTheDocument()
    })
})
