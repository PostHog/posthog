import { Button, Card, Text } from '@posthog/quill'

import type { MCPServerInstallationApi, MCPServerTemplateApi } from '../generated/api.schemas'
import { ServerIcon } from './icons'

export function QuillServerCard({
    server,
    installation,
    restrictedReason,
    onOpen,
    onConnect,
    onRemove,
}: {
    server: MCPServerTemplateApi
    installation: MCPServerInstallationApi | null | undefined
    restrictedReason: string | null
    onOpen: () => void
    onConnect: () => void
    onRemove: (installationId: string) => void
}): JSX.Element {
    return (
        <Card size="sm" className="p-0">
            <div className="flex items-center gap-2 pr-3">
                <button
                    type="button"
                    className="flex min-w-0 flex-1 items-center gap-3 px-3 py-2 text-left hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={onOpen}
                >
                    <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={40} />
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <Text size="sm" weight="medium" className="m-0 truncate" render={<span />}>
                            {server.name}
                        </Text>
                        {server.description && (
                            <Text size="xs" variant="muted" className="m-0 line-clamp-2" render={<span />}>
                                {server.description}
                            </Text>
                        )}
                    </span>
                </button>
                {installation ? (
                    <Button
                        variant="destructive-outline"
                        onClick={() => onRemove(installation.id)}
                        disabledReason={restrictedReason}
                    >
                        Remove
                    </Button>
                ) : (
                    <Button variant="primary" onClick={onConnect} disabledReason={restrictedReason}>
                        Connect
                    </Button>
                )}
            </div>
        </Card>
    )
}
