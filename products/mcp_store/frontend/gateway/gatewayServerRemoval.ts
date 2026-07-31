import type { MCPGatewayServerApi } from '../generated/api.schemas'

export type GatewayServerRemovalAction = 'delete_for_everyone' | 'delete_for_you' | 'disconnect'

export function getGatewayServerRemovalAction(
    server: MCPGatewayServerApi,
    isAdmin: boolean,
    currentUserId: number | undefined
): GatewayServerRemovalAction | null {
    if (isAdmin && server.template_id === null) {
        return 'delete_for_everyone'
    }

    const yourConnection = server.your_connection
    if (!yourConnection) {
        return null
    }

    const yourConnectionSummary = server.connections.find(
        (connection) => connection.installation_id === yourConnection.installation_id
    )
    const connectionOwnerId = currentUserId ?? yourConnectionSummary?.user.id
    const personallyAddedCustomServer =
        server.template_id === null && connectionOwnerId !== undefined && server.created_by?.id === connectionOwnerId

    return personallyAddedCustomServer ? 'delete_for_you' : 'disconnect'
}
