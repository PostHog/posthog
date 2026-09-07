import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { CreateInsightWidget } from './CreateInsightWidget'

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
jest.mock('scenes/urls', () => ({
    urls: {
        dashboard: (id: number): string => `/dashboard/${id}`,
        insightView: (id: string): string => `/insight/${id}`,
        insightNew: (): string => '/insights/new',
    },
}))
jest.mock('../DataToolRow', () => ({
    DataToolRow: ({ children }: { children: React.ReactNode }) => <div data-attr="data-tool-row">{children}</div>,
}))
jest.mock('../GenericMcpToolRenderer', () => ({
    GenericMcpToolRenderer: () => <div data-attr="generic-mcp-tool-renderer" />,
}))
jest.mock('./VisualizationWidget', () => ({
    VisualizationWidget: ({ extraActions }: { extraActions?: React.ReactNode }) => (
        <div data-attr="visualization-widget">{extraActions}</div>
    ),
    getArtifactOpenTarget: (): { url: string; tooltip: string } => ({
        url: '/insight/abc12345',
        tooltip: 'Open insight',
    }),
}))

function message(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey: 'insight-create',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        rawInput: { command: 'call insight-create {}' },
        innerInput: { dashboards: [7] },
        rawOutput: {
            short_id: 'abc12345',
            query: { kind: 'TrendsQuery' },
            dashboard_tiles: [{ id: 41, dashboard_id: 7, deleted: false }],
        },
        content: [],
        status: 'completed',
        ...overrides,
    }
}

describe('CreateInsightWidget', () => {
    afterEach(() => {
        cleanup()
        jest.mocked(posthog.capture).mockClear()
    })

    it.each(['pending', 'in_progress', 'failed'] as const)('falls back while the tool is %s', (status) => {
        render(<CreateInsightWidget isLastInGroup message={message({ status })} />)

        expect(screen.getByTestId('generic-mcp-tool-renderer')).toBeInTheDocument()
    })

    it('falls back for malformed insight output', () => {
        render(<CreateInsightWidget isLastInGroup message={message({ rawOutput: { short_id: 'abc12345' } })} />)

        expect(screen.getByTestId('generic-mcp-tool-renderer')).toBeInTheDocument()
    })

    it('renders a same-tab dashboard action only for validated dashboard membership', () => {
        render(<CreateInsightWidget isLastInGroup message={message()} />)

        const action = screen.getByRole('link', { name: 'Show on dashboard' })
        expect(action).toHaveAttribute('href', '/dashboard/7?highlightTileId=41')
        expect(action).not.toHaveAttribute('target', '_blank')

        fireEvent.click(action)
        expect(posthog.capture).toHaveBeenCalledWith('posthog ai dashboard reveal clicked', {
            source: 'tool_card',
            target_kind: 'tile',
        })
    })

    it('retains the visualization but omits the reveal action for mismatched dashboard membership', () => {
        render(
            <CreateInsightWidget
                isLastInGroup
                message={message({
                    rawOutput: {
                        short_id: 'abc12345',
                        query: { kind: 'TrendsQuery' },
                        dashboard_tiles: [{ id: 41, dashboard_id: 8, deleted: false }],
                    },
                })}
            />
        )

        expect(screen.getByTestId('visualization-widget')).toBeInTheDocument()
        expect(screen.queryByRole('link', { name: 'Show on dashboard' })).not.toBeInTheDocument()
    })
})
