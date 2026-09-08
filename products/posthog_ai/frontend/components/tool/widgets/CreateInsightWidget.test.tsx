import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { CreateInsightWidget } from './CreateInsightWidget'

jest.mock('posthog-js', () => ({ __esModule: true, default: { capture: jest.fn() } }))
jest.mock('scenes/urls', () => ({
    urls: {
        dashboard: (id: number, _highlightInsightId?: string, highlightTileId?: number): string =>
            `/dashboard/${id}${highlightTileId ? `?highlightTileId=${highlightTileId}` : ''}`,
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
    beforeEach(() => {
        initKeaTests()
    })

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
        expect(action).toHaveAttribute('href', '/project/997/dashboard/7?highlightTileId=41')
        expect(action).not.toHaveAttribute('target', '_blank')

        fireEvent.click(action)
        expect(posthog.capture).toHaveBeenCalledWith('posthog ai dashboard reveal clicked', {
            source: 'tool_card',
            target_kind: 'tile',
        })
    })

    it.each([
        ['mismatched dashboard membership', { dashboards: [7] }, [{ id: 41, dashboard_id: 8, deleted: false }]],
        [
            'ambiguous dashboard membership',
            { dashboards: [7] },
            [
                { id: 41, dashboard_id: 7, deleted: false },
                { id: 42, dashboard_id: 7, deleted: false },
            ],
        ],
        [
            'unsafe dashboard membership',
            { dashboards: [7] },
            [{ id: Number.MAX_SAFE_INTEGER + 1, dashboard_id: 7, deleted: false }],
        ],
    ])('falls back for %s', (_case, innerInput, dashboardTiles) => {
        render(
            <CreateInsightWidget
                isLastInGroup
                message={message({
                    innerInput,
                    rawOutput: {
                        short_id: 'abc12345',
                        query: { kind: 'TrendsQuery' },
                        dashboard_tiles: dashboardTiles,
                    },
                })}
            />
        )

        expect(screen.getByTestId('generic-mcp-tool-renderer')).toBeInTheDocument()
        expect(screen.queryByTestId('visualization-widget')).not.toBeInTheDocument()
    })

    it('keeps the visualization for a valid insight that did not request dashboard placement', () => {
        render(
            <CreateInsightWidget
                isLastInGroup
                message={message({
                    innerInput: { dashboards: [] },
                    rawOutput: {
                        short_id: 'abc12345',
                        query: { kind: 'TrendsQuery' },
                        dashboard_tiles: [],
                    },
                })}
            />
        )

        expect(screen.getByTestId('visualization-widget')).toBeInTheDocument()
        expect(screen.queryByRole('link', { name: 'Show on dashboard' })).not.toBeInTheDocument()
    })
})
