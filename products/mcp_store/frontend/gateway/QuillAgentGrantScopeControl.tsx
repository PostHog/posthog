import { useActions, useValues } from 'kea'

import { ToggleGroup, ToggleGroupItem, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { MCPAgentGrantScopeEnumApi } from '../generated/api.schemas'
import { AGENT_GRANT_SCOPE_OPTIONS } from './gatewayUtils'
import { agentServerAccessKey, mcpGatewayLogic } from './mcpGatewayLogic'

export function QuillAgentGrantScopeControl({
    accountId,
    serverId,
    scope,
}: {
    accountId: string
    serverId: string
    scope: MCPAgentGrantScopeEnumApi
}): JSX.Element {
    const { agentServerAccessLoadingKeys } = useValues(mcpGatewayLogic)
    const { setAgentServerAccess } = useActions(mcpGatewayLogic)
    const saving = agentServerAccessLoadingKeys.has(agentServerAccessKey(accountId, serverId))

    return (
        <ToggleGroup
            size="sm"
            value={[scope]}
            onValueChange={(next: string[]) => {
                const picked = AGENT_GRANT_SCOPE_OPTIONS.find((option) => option.value === next[0])

                if (picked) {
                    setAgentServerAccess(accountId, serverId, true, picked.value)
                }
            }}
            className="flex-wrap"
        >
            {AGENT_GRANT_SCOPE_OPTIONS.map((option) =>
                saving ? (
                    <ToggleGroupItem key={option.value} value={option.value} disabledReason="Saving your change">
                        {option.label}
                    </ToggleGroupItem>
                ) : (
                    <Tooltip key={option.value}>
                        <TooltipTrigger render={<ToggleGroupItem value={option.value} />}>
                            {option.label}
                        </TooltipTrigger>
                        <TooltipContent>{option.tooltip}</TooltipContent>
                    </Tooltip>
                )
            )}
        </ToggleGroup>
    )
}
