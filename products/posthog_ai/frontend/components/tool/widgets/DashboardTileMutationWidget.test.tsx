import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { DashboardTileMutationWidget } from './DashboardTileMutationWidget'

jest.mock('posthog-js', () => ({ __esModule: true, default: { capture: jest.fn() } }))
jest.mock('@posthog/lemon-ui', () => ({
    LemonButton: ({
        children,
        onClick,
        targetBlank,
        to,
    }: {
        children: React.ReactNode
        onClick?: () => void
        targetBlank?: boolean
        to: string
    }) => (
        <button role="link" href={to} target={targetBlank ? '_blank' : undefined} onClick={onClick}>
            {children}
        </button>
    ),
}))
jest.mock('scenes/urls', () => ({ urls: { dashboard: (id: number): string => `/dashboard/${id}` } }))
jest.mock('../DataToolRow', () => ({
    DataToolRow: ({ children }: { children: React.ReactNode }) => <div data-attr="data-tool-row">{children}</div>,
}))
jest.mock('../GenericMcpToolRenderer', () => ({
    GenericMcpToolRenderer: () => <div data-attr="generic-mcp-tool-renderer" />,
}))

function message(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey: 'dashboard-create-tile',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        rawInput: { command: 'call dashboard-create-tile {}' },
        innerInput: { dashboard_id: 7 },
        rawOutput: { id: 41, dashboard_id: 7 },
        content: [],
        status: 'completed',
        ...overrides,
    }
}

describe('DashboardTileMutationWidget', () => {
    afterEach(() => {
        cleanup()
        jest.mocked(posthog.capture).mockClear()
    })

    it.each(['pending', 'in_progress', 'failed'] as const)('falls back while the tool is %s', (status) => {
        render(<DashboardTileMutationWidget isLastInGroup message={message({ status })} />)

        expect(screen.getByTestId('generic-mcp-tool-renderer')).toBeInTheDocument()
    })

    it.each([
        ['malformed output', 'not a result', { dashboard_id: 7 }],
        ['mismatched dashboard', { id: 41, dashboard_id: 8 }, { dashboard_id: 7 }],
        [
            'ambiguous batch',
            {
                tiles: [
                    { id: 41, dashboard_id: 7 },
                    { id: 42, dashboard_id: 7 },
                ],
                dashboard_id: 7,
            },
            { dashboard_id: 7, widgets: [{}] },
        ],
    ])('falls back for %s', (_case, rawOutput, innerInput) => {
        render(<DashboardTileMutationWidget isLastInGroup message={message({ rawOutput, innerInput })} />)

        expect(screen.getByTestId('generic-mcp-tool-renderer')).toBeInTheDocument()
    })

    it('shows a validated single tile on its dashboard in the current tab', () => {
        const { container } = render(<DashboardTileMutationWidget isLastInGroup message={message()} />)

        const action = screen.getByRole('link', { name: 'Show on dashboard' })
        expect(action).toHaveAttribute('href', '/dashboard/7?highlightTileId=41')
        expect(action).not.toHaveAttribute('target', '_blank')
        expect(container.querySelector('.flex-wrap')).toBeInTheDocument()
        expect(container.querySelector('.min-w-0')).toBeInTheDocument()
        expect(container.querySelector('.truncate')).toBeInTheDocument()

        fireEvent.click(action)
        expect(posthog.capture).toHaveBeenCalledWith('posthog ai dashboard reveal clicked', {
            source: 'tool_card',
            target_kind: 'tile',
        })
    })

    it('opens a validated dashboard-only mutation in a new tab without exposing output data in telemetry', () => {
        render(
            <DashboardTileMutationWidget
                isLastInGroup
                message={message({
                    resolvedKey: 'dashboard-reorder-tiles',
                    rawInput: { command: 'call dashboard-reorder-tiles {}' },
                    innerInput: { dashboard_id: 7 },
                    rawOutput: { id: 7, name: 'Sensitive dashboard name' },
                })}
            />
        )

        const action = screen.getByRole('link', { name: 'View dashboard' })
        expect(action).toHaveAttribute('href', '/dashboard/7')
        expect(action).toHaveAttribute('target', '_blank')

        fireEvent.click(action)
        expect(posthog.capture).toHaveBeenCalledWith('posthog ai dashboard reveal clicked', {
            source: 'tool_card',
            target_kind: 'dashboard',
        })
        expect(JSON.stringify(jest.mocked(posthog.capture).mock.calls)).not.toContain('Sensitive dashboard name')
    })
})
