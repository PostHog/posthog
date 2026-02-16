import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconPlus, IconServer, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTable, LemonTag } from '@posthog/lemon-ui'

import api from 'lib/api'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { AddCustomServerModal } from './AddCustomServerModal'
import { MCPServer, MCPServerInstallation, mcpStoreLogic } from './mcpStoreLogic'

export const scene: SceneExport = {
    component: McpStoreScene,
    logic: mcpStoreLogic,
}

function ConnectOAuthButton({
    name,
    url,
    description,
    type = 'primary',
}: {
    name: string
    url: string
    description: string
    type?: 'primary' | 'secondary'
}): JSX.Element {
    const [loading, setLoading] = useState(false)

    return (
        <LemonButton
            type={type}
            size="small"
            loading={loading}
            onClick={async () => {
                setLoading(true)
                try {
                    const result = await api.mcpServerInstallations.installCustom({
                        name,
                        url,
                        auth_type: 'oauth',
                        description,
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

export function McpStoreScene(): JSX.Element {
    const { installations, installationsLoading, installedServerUrls, recommendedServers, serversLoading } =
        useValues(mcpStoreLogic)
    const { uninstallServer, openAddCustomServerModal } = useActions(mcpStoreLogic)
    const { currentTeamId } = useValues(teamLogic)
    const [searchTerm, setSearchTerm] = useState('')

    return (
        <SceneContent>
            <SceneTitleSection
                name="MCP servers"
                description="Manage MCP servers for your AI agents."
                resourceType={{ type: 'mcp_store' }}
                actions={
                    <LemonButton type="primary" icon={<IconPlus />} onClick={openAddCustomServerModal} size="small">
                        Add custom server
                    </LemonButton>
                }
            />

            <h3>Installed servers</h3>
            <LemonTable
                loading={installationsLoading}
                dataSource={installations}
                emptyState="No servers installed yet. Browse recommended servers below or add a custom one."
                columns={[
                    {
                        width: 0,
                        render: (_: any, installation: MCPServerInstallation) =>
                            installation.server?.icon_url ? (
                                <img src={installation.server.icon_url} alt="" className="w-6 h-6" />
                            ) : (
                                <IconServer className="text-muted text-xl" />
                            ),
                    },
                    {
                        title: 'Name',
                        render: (_: any, installation: MCPServerInstallation) => (
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
                        render: (_: any, installation: MCPServerInstallation) =>
                            installation.pending_oauth ? (
                                <ConnectOAuthButton
                                    name={installation.display_name || installation.name}
                                    url={installation.url}
                                    description={installation.description}
                                />
                            ) : installation.needs_reauth && installation.server ? (
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    onClick={() => {
                                        window.location.href = `/api/environments/${currentTeamId}/mcp_server_installations/authorize/?server_id=${installation.server!.id}`
                                    }}
                                >
                                    Reconnect
                                </LemonButton>
                            ) : (
                                <LemonTag type="success" icon={<IconCheck />}>
                                    Active
                                </LemonTag>
                            ),
                    },
                    {
                        width: 0,
                        render: (_: any, installation: MCPServerInstallation) => (
                            <More
                                overlay={
                                    <LemonMenuOverlay
                                        items={[
                                            {
                                                label: 'Uninstall',
                                                status: 'danger' as const,
                                                icon: <IconTrash />,
                                                onClick: () => uninstallServer(installation.id),
                                            },
                                        ]}
                                    />
                                }
                            />
                        ),
                    },
                ]}
            />

            {recommendedServers.length > 0 && (
                <>
                    <div className="flex-col items-center justify-between mt-4">
                        <h3 className="mb-4">Recommended servers</h3>
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
                            (s: MCPServer) =>
                                !searchTerm ||
                                s.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                                s.description.toLowerCase().includes(searchTerm.toLowerCase())
                        )}
                        columns={[
                            {
                                width: 0,
                                render: (_: any, server: MCPServer) =>
                                    server.icon_url ? <img src={server.icon_url} alt="" className="w-6 h-6" /> : null,
                            },
                            {
                                title: 'Name',
                                key: 'name',
                                sorter: (a: MCPServer, b: MCPServer) => a.name.localeCompare(b.name),
                                render: (_: any, server: MCPServer) => (
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
                                render: (_: any, server: MCPServer) =>
                                    installedServerUrls.has(server.url) ? (
                                        <LemonTag type="success" icon={<IconCheck />}>
                                            Active
                                        </LemonTag>
                                    ) : (
                                        <ConnectOAuthButton
                                            name={server.name}
                                            url={server.url}
                                            description={server.description}
                                            type="secondary"
                                        />
                                    ),
                            },
                        ]}
                    />
                </>
            )}

            <AddCustomServerModal />
        </SceneContent>
    )
}

export default scene
