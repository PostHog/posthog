import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { openRemoveAllSharesDialog } from './gatewayUtils'
import { agentServerAccessKey, mcpGatewayLogic } from './mcpGatewayLogic'

export function QuillRemoveAllSharesButton({
    accountId,
    accountName,
    serverId,
    serverName,
    shareCount,
}: {
    accountId: string
    accountName: string
    serverId: string
    serverName: string
    shareCount: number
}): JSX.Element | null {
    const { agentServerAccessLoadingKeys, isAdmin } = useValues(mcpGatewayLogic)
    const { removeAllAgentServerShares } = useActions(mcpGatewayLogic)

    if (!isAdmin || shareCount === 0) {
        return null
    }

    return (
        <Button
            variant="destructive-outline"
            loading={agentServerAccessLoadingKeys.has(agentServerAccessKey(accountId, serverId))}
            onClick={() =>
                openRemoveAllSharesDialog({
                    accountName,
                    serverName,
                    shareCount,
                    onConfirm: () => removeAllAgentServerShares(accountId, serverId),
                })
            }
        >
            Remove all shares
        </Button>
    )
}
