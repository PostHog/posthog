import { useActions, useValues } from 'kea'

import { Badge, Card, CardGroup, Heading, Text } from '@posthog/quill'

import type { MCPServerInstallationApi } from '../generated/api.schemas'
import { mcpStoreLogic } from '../mcpStoreLogic'
import { ServerIcon } from './icons'

function InstallationStatusBadge({ installation }: { installation: MCPServerInstallationApi }): JSX.Element {
    if (installation.pending_oauth) {
        return <Badge variant="warning">Pending OAuth</Badge>
    }

    if (installation.needs_reauth) {
        return <Badge variant="destructive">Reconnect</Badge>
    }

    if (installation.is_enabled === false) {
        return <Badge>Disabled</Badge>
    }

    return <Badge variant="success">Connected</Badge>
}

export function QuillInstalledServersList(): JSX.Element | null {
    const { installations, filteredInstallations } = useValues(mcpStoreLogic)
    const { selectServer } = useActions(mcpStoreLogic)

    if (installations.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <Heading size="sm" render={<h3 className="m-0" />}>
                Installed
            </Heading>
            {filteredInstallations.length === 0 ? (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    No installed servers match your search.
                </Text>
            ) : (
                <CardGroup size="sm">
                    {filteredInstallations.map((installation) => {
                        const toolCount = installation.tool_count ?? 0

                        return (
                            <Card key={installation.id} size="sm" className="p-0">
                                <button
                                    type="button"
                                    className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                    onClick={() => selectServer(installation.id)}
                                >
                                    <ServerIcon
                                        iconDomain={installation.icon_domain}
                                        serverUrl={installation.url}
                                        size={32}
                                    />
                                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                                        <Text size="sm" weight="medium" className="m-0 truncate" render={<span />}>
                                            {installation.name}
                                        </Text>
                                        <Text size="xs" variant="muted" className="m-0 truncate" render={<span />}>
                                            {`${toolCount} tool${toolCount === 1 ? '' : 's'}${
                                                installation.description ? ` · ${installation.description}` : ''
                                            }`}
                                        </Text>
                                    </span>
                                    <span className="flex shrink-0 flex-wrap items-center gap-1">
                                        {installation.scope === 'shared' && <Badge variant="info">Shared</Badge>}
                                        <InstallationStatusBadge installation={installation} />
                                    </span>
                                </button>
                            </Card>
                        )
                    })}
                </CardGroup>
            )}
        </div>
    )
}
