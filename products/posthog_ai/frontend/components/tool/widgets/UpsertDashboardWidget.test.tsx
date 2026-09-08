import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { UpsertDashboardWidget } from './UpsertDashboardWidget'

jest.mock('posthog-js', () => ({ __esModule: true, default: { capture: jest.fn() } }))
jest.mock('scenes/urls', () => ({
    urls: {
        dashboard: (id: number, _highlightInsightId?: string, highlightTileId?: number): string =>
            `/dashboard/${id}${highlightTileId ? `?highlightTileId=${highlightTileId}` : ''}`,
    },
}))
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
    beforeEach(() => {
        initKeaTests()
    })

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
        expect(action).toHaveAttribute('href', '/project/997/dashboard/7')
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

    it.each([
        ['an empty object', {}],
        ['zero', { id: 0 }],
        ['a negative number', { id: -1 }],
        ['a decimal', { id: 1.5 }],
        ['an unsafe integer', { id: Number.MAX_SAFE_INTEGER + 1 }],
        ['a string', { id: '7' }],
        ['an arbitrary object', { name: 'Dashboard', url: '/dashboard/7' }],
        ['unstructured text', 'created dashboard 7'],
    ])('falls back when dashboard-create returns %s', (_case, rawOutput) => {
        render(
            <UpsertDashboardWidget
                isLastInGroup
                message={message({ resolvedKey: 'dashboard-create', innerInput: { name: 'New dashboard' }, rawOutput })}
            />
        )

        expect(screen.getByTestId('generic-mcp-tool-renderer')).toBeInTheDocument()
        expect(screen.queryByRole('link', { name: 'View dashboard' })).not.toBeInTheDocument()
    })

    it('keeps its label and action responsive in a 520px container', () => {
        const { container } = render(
            <div data-attr="narrow-container" style={{ width: 520 }}>
                <UpsertDashboardWidget
                    isLastInGroup
                    message={message({
                        rawOutput: {
                            id: 7,
                            name: 'A dashboard name that is intentionally long enough to require truncation',
                        },
                    })}
                />
            </div>
        )

        expect(screen.getByTestId('narrow-container')).toHaveStyle({ width: '520px' })
        expect(container.querySelector('.flex-wrap')).toBeInTheDocument()
        expect(screen.getByText(/intentionally long/)).toHaveClass('min-w-0', 'truncate')
        expect(screen.getByRole('link', { name: 'View dashboard' })).toHaveClass('shrink-0')
    })
})
