import { useActions, useValues } from 'kea'

import { LemonCard, LemonTag } from '@posthog/lemon-ui'

import { mcpStoreLogic } from '../mcpStoreLogic'
import { ServerIcon } from './icons'

export function InstalledServersList(): JSX.Element | null {
    const { installations, filteredInstallations } = useValues(mcpStoreLogic)
    const { selectServer } = useActions(mcpStoreLogic)

    if (installations.length === 0) {
        return null
    }

    return (
        <div className="deprecated-space-y-2">
            <h2 className="mb-0 text-base font-semibold">Installed</h2>

            {filteredInstallations.length === 0 ? (
                <div className="text-sm text-secondary px-1 py-2">No installed servers match your search.</div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
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
                                    <ServerIcon iconKey={null} name={installation.name} size={32} />
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
