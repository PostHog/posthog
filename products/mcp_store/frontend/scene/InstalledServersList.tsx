import { useActions, useValues } from 'kea'

import { LemonCard, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { mcpStoreLogic } from '../mcpStoreLogic'
import { ServerIcon } from './icons'

export function InstalledServersList(): JSX.Element | null {
    const { filteredInstallations, filteredBuiltinServers } = useValues(mcpStoreLogic)
    const { selectServer } = useActions(mcpStoreLogic)

    const hasResults = filteredBuiltinServers.length > 0 || filteredInstallations.length > 0

    return (
        <div className="deprecated-space-y-2">
            <h2 className="mb-0 text-base font-semibold">Installed</h2>

            {!hasResults ? (
                <div className="text-sm text-secondary px-1 py-2">No installed servers match your search.</div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                    {filteredBuiltinServers.map((server) => (
                        <Tooltip
                            key={server.id}
                            title="Built-in — automatically available in every PostHog Code session. It can't be disabled or removed."
                        >
                            <LemonCard className="cursor-default">
                                <div className="flex items-center gap-3">
                                    <ServerIcon iconKey={server.icon_key} size={32} />
                                    <div className="flex-1 min-w-0">
                                        <h4 className="mb-0 truncate">{server.name}</h4>
                                        <div className="text-xs text-secondary truncate">{server.description}</div>
                                    </div>
                                    <LemonTag type="highlight" size="small">
                                        Built-in
                                    </LemonTag>
                                </div>
                            </LemonCard>
                        </Tooltip>
                    ))}

                    {filteredInstallations.map((installation) => {
                        const statusTag = installation.pending_oauth ? (
                            <LemonTag type="warning" size="small">
                                Pending OAuth
                            </LemonTag>
                        ) : installation.needs_reauth ? (
                            <LemonTag type="danger" size="small">
                                Reconnect
                            </LemonTag>
                        ) : installation.is_enabled === false ? (
                            <LemonTag type="muted" size="small">
                                Disabled
                            </LemonTag>
                        ) : (
                            <LemonTag type="success" size="small">
                                Connected
                            </LemonTag>
                        )

                        const toolCount = installation.tool_count ?? 0

                        return (
                            <LemonCard
                                key={installation.id}
                                hoverEffect
                                className="cursor-pointer"
                                onClick={() => selectServer(installation.id)}
                            >
                                <div className="flex items-center gap-3">
                                    <ServerIcon iconKey={installation.icon_key} size={32} />
                                    <div className="flex-1 min-w-0">
                                        <h4 className="mb-0 truncate">{installation.name}</h4>
                                        <div className="text-xs text-secondary truncate">
                                            {toolCount} tool{toolCount === 1 ? '' : 's'}
                                            {installation.description ? ` · ${installation.description}` : ''}
                                        </div>
                                    </div>
                                    {statusTag}
                                </div>
                            </LemonCard>
                        )
                    })}
                </div>
            )}
        </div>
    )
}
