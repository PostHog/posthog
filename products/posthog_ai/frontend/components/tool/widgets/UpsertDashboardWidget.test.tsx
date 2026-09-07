import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { UpsertDashboardWidget } from './UpsertDashboardWidget'

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
        resolvedKey: 'dashboard-update',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        rawInput: { command: 'call dashboard-update {}' },
        innerInput: { id: 7 },
        rawOutput: { id: 7, name: 'Sensitive dashboard name' },
        content: [],
        status: 'completed',
        ...overrides,
    }
}

describe('UpsertDashboardWidget', () => {
    afterEach(() => {
        cleanup()
        jest.mocked(posthog.capture).mockClear()
    })

    it.each(['pending', 'in_progress', 'failed'] as const)('falls back while the tool is %s', (status) => {
        render(<UpsertDashboardWidget isLastInGroup message={message({ status })} />)

        expect(screen.getByTestId('generic-mcp-tool-renderer')).toBeInTheDocument()
    })

    it.each([
        ['malformed output', 'not a result'],
        ['mismatched response id', { id: 8, name: 'Sensitive dashboard name' }],
    ])('falls back for %s', (_case, rawOutput) => {
        render(<UpsertDashboardWidget isLastInGroup message={message({ rawOutput })} />)

        expect(screen.getByTestId('generic-mcp-tool-renderer')).toBeInTheDocument()
    })

    it('shows a validated update as a dashboard link in a new tab with private telemetry', () => {
        const { container } = render(<UpsertDashboardWidget isLastInGroup message={message()} />)

        const action = screen.getByRole('link', { name: 'View dashboard' })
        expect(action).toHaveAttribute('href', '/dashboard/7')
        expect(action).toHaveAttribute('target', '_blank')
        expect(container.querySelector('.flex-wrap')).toBeInTheDocument()
        expect(container.querySelector('.min-w-0')).toBeInTheDocument()
        expect(container.querySelector('.truncate')).toBeInTheDocument()

        fireEvent.click(action)
        expect(posthog.capture).toHaveBeenCalledWith('posthog ai dashboard reveal clicked', {
            source: 'tool_card',
            target_kind: 'dashboard',
        })
        expect(JSON.stringify(jest.mocked(posthog.capture).mock.calls)).not.toContain('Sensitive dashboard name')
    })

    it('keeps dashboard-create links opening in a new tab', () => {
        render(
            <UpsertDashboardWidget
                isLastInGroup
                message={message({ resolvedKey: 'dashboard-create', innerInput: { name: 'New dashboard' } })}
            />
        )

        expect(screen.getByRole('link', { name: 'View dashboard' })).toHaveAttribute('target', '_blank')
    })
})
