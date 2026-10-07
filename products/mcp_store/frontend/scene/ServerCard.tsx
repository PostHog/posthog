import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import type { MCPServerTemplateApi } from '../generated/api.schemas'
import { mcpStoreLogic } from '../mcpStoreLogic'
import { ServerIcon } from './icons'

interface Props {
    server: MCPServerTemplateApi
}

export function ServerCard({ server }: Props): JSX.Element {
    const { installedServerUrls, installations, installingTemplateId } = useValues(mcpStoreLogic)
    const { connectTemplate, selectServer, uninstallServer } = useActions(mcpStoreLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })

    const isInstalled = installedServerUrls.has(server.url)
    const installation = isInstalled ? installations.find((i) => i.url === server.url) : null

    const openDetail = (): void => {
        selectServer(installation ? installation.id : server.id)
    }

    return (
        <LemonCard hoverEffect className="cursor-pointer" onClick={openDetail}>
            <div className="flex gap-3 flex-row items-center">
                <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={40} />
                <div className="flex-1 min-w-0">
                    <h3 className="mb-0 truncate">{server.name}</h3>
                    {server.description && (
                        <p className="text-sm text-secondary mt-1 mb-0 line-clamp-2">{server.description}</p>
                    )}
                </div>
                {isInstalled && installation ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        status="danger"
                        onClick={() => uninstallServer(installation.id)}
                        disabledReason={restrictedReason}
                        stopPropagation
                    >
                        Remove
                    </LemonButton>
                ) : (
                    <LemonButton
                        size="small"
                        type="primary"
                        onClick={() => connectTemplate(server)}
                        loading={installingTemplateId === server.id}
                        disabledReason={restrictedReason}
                        stopPropagation
                    >
                        Connect
                    </LemonButton>
                )}
            </div>
        </LemonCard>
    )
}
