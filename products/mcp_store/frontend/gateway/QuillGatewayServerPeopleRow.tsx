import { AvatarGroup, Text } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { fullName } from 'lib/utils/strings'

import { GatewayServerEntry } from './mcpGatewayLogic'

export function QuillGatewayServerPeopleRow({ server }: { server: GatewayServerEntry }): JSX.Element {
    if (!server.is_team_enabled) {
        return (
            <Text size="xs" variant="muted" render={<span className="m-0" />}>
                Disabled. Enable it in Team settings.
            </Text>
        )
    }

    const connections = server.connections ?? []
    // `agents` holds one row per member grant, so an agent repeats once per member sharing it.
    const agentCount = new Set((server.agents ?? []).map((agent) => agent.service_account_id)).size

    const connectedLabel =
        connections.length === 0
            ? 'No one connected yet'
            : `${connections.length} teammate${connections.length === 1 ? '' : 's'} connected`
    const agentLabel = agentCount > 0 ? ` · ${agentCount} agent${agentCount === 1 ? '' : 's'}` : ''

    return (
        <span className="flex items-center gap-2">
            {connections.length > 0 && (
                <AvatarGroup stacked size="xs">
                    {connections.slice(0, 4).map((connection) => (
                        <QuillPersonAvatar
                            key={connection.installation_id}
                            name={fullName(connection.user)}
                            email={connection.user.email}
                            size="xs"
                        />
                    ))}
                </AvatarGroup>
            )}
            <Text size="xs" variant="muted" render={<span className="m-0" />}>
                {`${connectedLabel}${agentLabel}`}
            </Text>
        </span>
    )
}
