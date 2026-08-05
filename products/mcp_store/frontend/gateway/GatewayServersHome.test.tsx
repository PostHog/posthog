import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import type { MouseEventHandler, ReactNode } from 'react'

import type { MCPGatewayServerApi } from '../generated/api.schemas'
import { GatewayServerCard, GatewayServersLoadError } from './GatewayServersHome'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    LemonBanner: ({
        children,
        action,
    }: {
        children: ReactNode
        action: { children: ReactNode; onClick: () => void }
    }) => (
        <div>
            {children}
            <button onClick={action.onClick}>{action.children}</button>
        </div>
    ),
    LemonButton: ({
        children,
        onClick,
        stopPropagation,
    }: {
        children: ReactNode
        onClick?: MouseEventHandler<HTMLButtonElement>
        stopPropagation?: boolean
    }) => (
        <button
            onClick={(event) => {
                if (stopPropagation) {
                    event.stopPropagation()
                }
                onClick?.(event)
            }}
        >
            {children}
        </button>
    ),
    LemonTag: ({ children }: { children: ReactNode }) => <span>{children}</span>,
    Tooltip: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

jest.mock('../scene/icons', () => ({
    ServerIcon: (): JSX.Element => <span data-testid="server-icon" />,
}))

function gatewayServer(): MCPGatewayServerApi {
    return {
        id: 'server-id',
        name: 'Test server',
        url: 'https://mcp.example.com/mcp',
        description: '',
        category: 'dev',
        template_auth_type: null,
        is_team_enabled: true,
        icon_key: '',
        icon_domain: '',
        docs_url: '',
        template_id: null,
        tool_count: 0,
        connections: [],
        your_connection: null,
        agents: [],
        revoked_user_ids: [],
        is_revoked_for_you: false,
        created_by: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    }
}

describe('GatewayServersHome', () => {
    const connectServer = jest.fn()
    const reconnectServer = jest.fn()

    beforeEach(() => {
        jest.mocked(useValues).mockReturnValue({ isAdmin: false, connectingServerId: null })
        jest.mocked(useActions).mockReturnValue({ connectServer, reconnectServer })
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    it.each([
        [false, "Couldn't load MCP servers. Try again."],
        [true, "Couldn't load this MCP server. Try again."],
    ])('renders a retryable load error for serverDetail=%s', (serverDetail, message) => {
        const onRetry = jest.fn()

        render(<GatewayServersLoadError serverDetail={serverDetail} onRetry={onRetry} />)

        expect(screen.getByText(message)).toBeInTheDocument()
        fireEvent.click(screen.getByText('Try again'))
        expect(onRetry).toHaveBeenCalledTimes(1)
    })

    it('opens a server from the row without opening it from the Connect action', () => {
        const openServer = jest.fn()

        render(<GatewayServerCard server={gatewayServer()} onOpenServer={openServer} />)

        fireEvent.click(screen.getByText('Test server'))
        expect(openServer).toHaveBeenCalledWith('server-id')

        fireEvent.click(screen.getByText('Connect'))
        expect(connectServer).toHaveBeenCalledWith('server-id')
        expect(openServer).toHaveBeenCalledTimes(1)
    })
})
