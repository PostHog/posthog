import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useState } from 'react'

import { IconCheck, IconPlus, IconRefresh, IconServer, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'

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
import type {
    MCPServerInstallationApi,
    MCPServerInstallationToolApi,
    MCPServerTemplateApi,
} from './generated/api.schemas'
import { type ToolApprovalState, mcpStoreLogic } from './mcpStoreLogic'

const SERVER_ICONS: Record<string, string> = {
    PostHog: IconPostHogService,
    'PostHog MCP': IconPostHogService,
    Linear: IconLinearService,
    GitHub: IconGitHubService,
    Notion: IconNotionService,
    Monday: IconMondayService,
    Canva: IconCanvaService,
    Attio: IconAttioService,
    Atlassian: IconAtlassianService,
}

const TOOL_APPROVAL_OPTIONS: { value: ToolApprovalState; label: string }[] = [
    { value: 'approved', label: 'Approved' },
    { value: 'needs_approval', label: 'Needs approval' },
    { value: 'do_not_use', label: 'Do not use' },
]

function resolveIcon(key: string | undefined | null): string | undefined {
    if (!key) {
        return undefined
    }
    return SERVER_ICONS[key]
}

function InstallationToolsPanel({ installationId }: { installationId: string }): JSX.Element {
    const { installationTools, installationToolsLoading } = useValues(mcpStoreLogic)
    const { loadInstallationTools, refreshInstallationTools, setToolApprovalState } = useActions(mcpStoreLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })

    useEffect(() => {
        if (!installationTools[installationId]) {
            loadInstallationTools({ installationId })
        }
    }, [installationId, installationTools, loadInstallationTools])

    const tools = installationTools[installationId] ?? []
    const visibleTools = tools.filter((t) => !t.removed_at)

    return (
        <div className="deprecated-space-y-2 p-2">
            <div className="flex items-center justify-between">
                <h4 className="mb-0 text-xs font-semibold uppercase text-secondary">Tools</h4>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={() => refreshInstallationTools({ installationId })}
                    loading={installationToolsLoading}
                    disabledReason={restrictedReason}
                >
                    Refresh tools
                </LemonButton>
            </div>
            {visibleTools.length === 0 ? (
                <div className="text-muted text-xs">
                    {installationToolsLoading
                        ? 'Loading tools…'
                        : 'No tools reported yet. Click "Refresh tools" after connecting.'}
                </div>
            ) : (
                <LemonTable
                    size="small"
                    embedded
                    dataSource={visibleTools}
                    columns={[
                        {
                            title: 'Name',
                            render: (_: any, tool: MCPServerInstallationToolApi) => (
                                <div>
                                    <span className="font-semibold">{tool.display_name || tool.tool_name}</span>
                                    {tool.description && <div className="text-muted text-xs">{tool.description}</div>}
                                </div>
                            ),
                        },
                        {
                            title: 'Approval',
                            width: 0,
                            render: (_: any, tool: MCPServerInstallationToolApi) => (
                                <LemonSegmentedButton
                                    size="xsmall"
                                    value={(tool.approval_state ?? 'needs_approval') as ToolApprovalState}
                                    options={TOOL_APPROVAL_OPTIONS}
                                    onChange={(value) =>
                                        setToolApprovalState({
                                            installationId,
                                            toolName: tool.tool_name,
                                            approvalState: value,
                                        })
                                    }
                                    disabledReason={restrictedReason ?? undefined}
                                />
                            ),
                        },
                    ]}
                />
            )}
        </div>
    )
}

export function McpStoreSettings(): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })
    const { installations, installationsLoading, installedServerUrls, recommendedServers, serversLoading } =
        useValues(mcpStoreLogic)
    const {
        uninstallServer,
        toggleServerEnabled,
        openAddCustomServerModal,
        openAddCustomServerModalWithDefaults,
        installTemplate,
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
                expandable={{
                    // Only installations that have completed OAuth can meaningfully report tools.
                    rowExpandable: (installation) => !installation.pending_oauth && !installation.needs_reauth,
                    expandedRowRender: (installation) => <InstallationToolsPanel installationId={installation.id} />,
                }}
                columns={[
                    {
                        width: 0,
                        render: (_: any, installation: MCPServerInstallationApi) => {
                            const iconSrc = resolveIcon(installation.name)
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
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        onClick={() => {
                                            window.location.href = `/api/environments/${currentTeamId}/mcp_server_installations/authorize/?installation_id=${installation.id}`
                                        }}
                                        disabledReason={restrictedReason}
                                    >
                                        Connect
                                    </LemonButton>
                                ) : installation.needs_reauth ? (
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        onClick={() => {
                                            window.location.href = `/api/environments/${currentTeamId}/mcp_server_installations/authorize/?installation_id=${installation.id}`
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
                            (s: MCPServerTemplateApi) =>
                                !searchTerm ||
                                s.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                                (s.description ?? '').toLowerCase().includes(searchTerm.toLowerCase())
                        )}
                        columns={[
                            {
                                width: 0,
                                render: (_: any, server: MCPServerTemplateApi) => {
                                    const iconSrc = resolveIcon(server.icon_key) ?? resolveIcon(server.name)
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
                                sorter: (a: MCPServerTemplateApi, b: MCPServerTemplateApi) =>
                                    a.name.localeCompare(b.name),
                                render: (_: any, server: MCPServerTemplateApi) => (
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
                                render: (_: any, server: MCPServerTemplateApi) => (
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
                                                        template_id: server.id,
                                                    })
                                                }
                                                disabledReason={restrictedReason}
                                            >
                                                Connect
                                            </LemonButton>
                                        ) : (
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                onClick={() => installTemplate({ templateId: server.id })}
                                                disabledReason={restrictedReason}
                                            >
                                                Connect
                                            </LemonButton>
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
