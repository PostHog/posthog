import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { MCPServerTemplateApi } from '../generated/api.schemas'
import { mcpStoreLogic } from '../mcpStoreLogic'
import { ServerIcon } from './icons'
import { QuillServerCard } from './QuillServerCard'

interface Props {
    server: MCPServerTemplateApi
}

export function ServerCard({ server }: Props): JSX.Element {
    const { installedServerUrls, installations } = useValues(mcpStoreLogic)
    const { installTemplate, openAddCustomServerModalWithDefaults, selectServer, uninstallServer } =
        useActions(mcpStoreLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const isInstalled = installedServerUrls.has(server.url)
    const installation = isInstalled ? installations.find((i) => i.url === server.url) : null

    const openDetail = (): void => {
        selectServer(installation ? installation.id : server.id)
    }

    const handleConnect = (): void => {
        if (server.auth_type === 'api_key') {
            openAddCustomServerModalWithDefaults({
                name: server.name,
                url: server.url,
                description: server.description,
                auth_type: 'api_key',
                template_id: server.id,
            })
        } else {
            installTemplate({ templateId: server.id })
        }
    }

    if (todayRailNav) {
        return (
            <QuillServerCard
                server={server}
                installation={isInstalled ? installation : null}
                restrictedReason={restrictedReason}
                onOpen={openDetail}
                onConnect={handleConnect}
                onRemove={uninstallServer}
            />
        )
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
                        onClick={handleConnect}
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
