import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { mcpGatewayLogic } from './mcpGatewayLogic'

export function GatewayServersSearch(): JSX.Element {
    const { searchQuery } = useValues(mcpGatewayLogic)
    const { setSearchQuery } = useActions(mcpGatewayLogic)

    return (
        <LemonInput
            type="search"
            placeholder="Search MCP servers…"
            value={searchQuery}
            onChange={setSearchQuery}
            fullWidth
            aria-label="Search MCP servers"
        />
    )
}
