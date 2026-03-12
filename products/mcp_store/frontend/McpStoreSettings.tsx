import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useState } from 'react'

import { IconCheck, IconPlus, IconServer, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'

import api from 'lib/api'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { teamLogic } from 'scenes/teamLogic'

import IconPostHogService from 'public/posthog-icon.svg'
import IconAtlassianService from 'public/services/atlassian.svg'
import IconAttioService from 'public/services/attio.png'
import IconCanvaService from 'public/services/canva.svg'
import IconGitHubService from 'public/services/github.svg'
import IconLinearService from 'public/services/linear.svg'
import IconMondayService from 'public/services/monday.svg'
import IconNotionService from 'public/services/notion.svg'

import { AddCustomServerModal } from './AddCustomServerModal'
import type { MCPServerInstallationApi, RecommendedServerApi } from './generated/api.schemas'
import { mcpStoreLogic } from './mcpStoreLogic'

const SERVER_ICONS: Record<string, string> = {
    'PostHog MCP': IconPostHogService,
    Linear: IconLinearService,
    GitHub: IconGitHubService,
    Notion: IconNotionService,
    Monday: IconMondayService,
    Canva: IconCanvaService,
    Attio: IconAttioService,
    Atlassian: IconAtlassianService,
}

function ConnectOAuthButton({
    name,
    url,
    description,
    oauthProviderKind,
    type = 'primary',
    disabledReason,
}: {
    name: string
    url: string
    description: string
    oauthProviderKind?: string
    type?: 'primary' | 'secondary'
    disabledReason?: string | null
}): JSX.Element {
    const [loading, setLoading] = useState(false)

    return (
        <LemonButton
            type={type}
            size="small"
            loading={loading}
            disabledReason={disabledReason}
            onClick={async () => {
                setLoading(true)
                try {
                    const result = await api.mcpServerInstallations.installCustom({
                        name,
                        url,
                        auth_type: 'oauth',
                        description,
                        ...(oauthProviderKind ? { oauth_provider_kind: oauthProviderKind } : {}),
                    })
                    if (result?.redirect_url) {
                        window.location.href = result.redirect_url
                    }
                } catch {
                    setLoading(false)
                }
            }}
        >
            Connect
        </LemonButton>
    )
}

export function McpStoreSettings(): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const { installations, installationsLoading, installedServerUrls, recommendedServers, serversLoading } =
        useValues(mcpStoreLogic)
    const {
        uninstallServer,
        toggleServerEnabled,
        openAddCustomServerModal,
        openAddCustomServerModalWithDefaults,
        loadInstallations,
        loadServers,
    } = useActions(mcpStoreLogic)
    const { currentTeamId } = useValues(teamLogic)
    const [searchTerm, setSearchTerm] = useState('')

    const refreshMcpStoreState = useCallback(() => {
        loadInstallations()
        loadServers()
    }, [loadInstallations, loadServers])

    useEffect(() => {
        const handleVisibilityChange = (): void => {
            if (document.visibilityState === 'visible') {
                refreshMcpStoreState()
            }
        }

        window.addEventListener('focus', refreshMcpStoreState)
        document.addEventListener('visibilitychange', handleVisibilityChange)

        return () => {
            window.removeEventListener('focus', refreshMcpStoreState)
            document.removeEventListener('visibilitychange', handleVisibilityChange)
        }
    }, [refreshMcpStoreState])

    return (
        <>
            <div className="flex items-center justify-between mb-4">
                <h3 className="mb-0">Installed servers</h3>
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={openAddCustomServerModal}
                    size="small"
                    disabledReason={restrictedReason}
                >
                    Add custom server
                </LemonButton>
            </div>
            <LemonTable
                loading={installationsLoading}
                dataSource={installations}
                emptyState="No servers installed yet. Browse recommended servers below or add a custom one."
                columns={[
                    {
                        width: 0,
                        render: (_: any, installation: MCPServerInstallationApi) => {
                            const iconSrc = SERVER_ICONS[installation.name]
                            return iconSrc ? (
                                <div className="w-6 h-6 flex items-center justify-center">
                                    <img src={iconSrc} alt="" className="w-6 h-6" />
                                </div>
                            ) : (
                                <div className="w-6 h-6 flex items-center justify-center">
                                    <IconServer className="text-muted text-xl" />
                                </div>
                            )
                        },
                    },
                    {
                        title: 'Name',
                        render: (_: any, installation: MCPServerInstallationApi) => (
                            <div>
                                <span className="font-semibold">{installation.name}</span>
                                {installation.description && (
                                    <div className="text-muted text-xs">{installation.description}</div>
                                )}
                            </div>
                        ),
                    },
                    {
                        width: 0,
                        render: (_: any, installation: MCPServerInstallationApi) => (
                            <div className="flex items-center justify-end">
                                {installation.pending_oauth ? (
                                    <ConnectOAuthButton
                                        name={installation.display_name || installation.name}
                                        url={installation.url ?? ''}
                                        description={installation.description ?? ''}
                                        disabledReason={restrictedReason}
                                    />
                                ) : installation.needs_reauth && installation.server_id ? (
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        onClick={() => {
                                            window.location.href = `/api/environments/${currentTeamId}/mcp_server_installations/authorize/?server_id=${installation.server_id}`
                                        }}
                                        disabledReason={restrictedReason}
                                    >
                                        Reconnect
                                    </LemonButton>
                                ) : (
                                    <LemonSwitch
                                        checked={installation.is_enabled !== false}
                                        onChange={(checked) =>
                                            toggleServerEnabled({ id: installation.id, enabled: checked })
                                        }
                                        size="small"
                                        disabledReason={restrictedReason}
                                    />
                                )}
                            </div>
                        ),
                    },
                    {
                        width: 0,
                        render: (_: any, installation: MCPServerInstallationApi) => (
                            <More
                                overlay={
                                    <LemonMenuOverlay
                                        items={[
                                            {
                                                label: 'Uninstall',
                                                status: 'danger' as const,
                                                icon: <IconTrash />,
                                                onClick: () => uninstallServer(installation.id),
                                                disabledReason: restrictedReason ?? undefined,
                                            },
                                        ]}
                                    />
                                }
                                disabledReason={restrictedReason}
                            />
                        ),
                    },
                ]}
            />

            {recommendedServers.length > 0 && (
                <>
                    <div className="flex-col items-center justify-between mt-4 mb-2">
                        <h3 className="mb-4">Pre-configured servers</h3>
                        <LemonInput
                            type="search"
                            placeholder="Search MCP servers..."
                            value={searchTerm}
                            onChange={setSearchTerm}
                        />
                    </div>
                    <LemonTable
                        loading={serversLoading}
                        dataSource={recommendedServers.filter(
                            (s: RecommendedServerApi) =>
                                !searchTerm ||
                                s.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                                s.description.toLowerCase().includes(searchTerm.toLowerCase())
                        )}
                        columns={[
                            {
                                width: 0,
                                render: (_: any, server: RecommendedServerApi) => {
                                    const iconSrc = SERVER_ICONS[server.name]
                                    return iconSrc ? (
                                        <div className="w-6 h-6 flex items-center justify-center">
                                            <img src={iconSrc} alt="" className="w-6 h-6" />
                                        </div>
                                    ) : (
                                        <div className="w-6 h-6 flex items-center justify-center">
                                            <IconServer className="text-muted text-xl" />
                                        </div>
                                    )
                                },
                            },
                            {
                                title: 'Name',
                                key: 'name',
                                sorter: (a: RecommendedServerApi, b: RecommendedServerApi) =>
                                    a.name.localeCompare(b.name),
                                render: (_: any, server: RecommendedServerApi) => (
                                    <div>
                                        <span className="font-semibold">{server.name}</span>
                                        {server.description && (
                                            <div className="text-muted text-xs">{server.description}</div>
                                        )}
                                    </div>
                                ),
                            },
                            {
                                width: 0,
                                render: (_: any, server: RecommendedServerApi) => (
                                    <div className="flex items-center justify-end">
                                        {installedServerUrls.has(server.url) ? (
                                            <LemonTag type="success" icon={<IconCheck />}>
                                                Active
                                            </LemonTag>
                                        ) : server.auth_type === 'api_key' ? (
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                onClick={() =>
                                                    openAddCustomServerModalWithDefaults({
                                                        name: server.name,
                                                        url: server.url,
                                                        description: server.description,
                                                        auth_type: 'api_key',
                                                    })
                                                }
                                                disabledReason={restrictedReason}
                                            >
                                                Connect
                                            </LemonButton>
                                        ) : (
                                            <ConnectOAuthButton
                                                name={server.name}
                                                url={server.url}
                                                description={server.description}
                                                oauthProviderKind={server.oauth_provider_kind}
                                                type="secondary"
                                                disabledReason={restrictedReason}
                                            />
                                        )}
                                    </div>
                                ),
                            },
                        ]}
                    />
                </>
            )}

            <AddCustomServerModal />
        </>
    )
}
