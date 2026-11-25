import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export function QuillGatewayToolPoliciesButton({
    serverId,
    scope,
    onOpenServer,
}: {
    serverId: string
    scope: string
    onOpenServer?: (serverId: string, scope: string) => void
}): JSX.Element {
    if (onOpenServer) {
        return (
            <Button variant="outline" onClick={() => onOpenServer(serverId, scope)}>
                Tool policies
            </Button>
        )
    }

    return (
        <Button
            variant="outline"
            nativeButton={false}
            render={<LinkPrimitive to={urls.mcpGatewayServer(serverId, scope)} />}
        >
            Tool policies
        </Button>
    )
}
