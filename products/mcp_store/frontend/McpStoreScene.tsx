import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPlug, IconPlus, IconTrash, IconWarning } from '@posthog/icons'
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

function ServerConfigRow({ server }: { server: MCPServer }): JSX.Element {
    const { installServer, setConfiguringServerId } = useActions(mcpStoreLogic)
    const [apiKey, setApiKey] = useState('')

    return (
        <div className="flex items-center gap-2 py-1">
            <LemonInput
                value={apiKey}
                onChange={setApiKey}
                placeholder="Enter API key"
                type="password"
                fullWidth
                size="small"
            />
            <LemonButton
                type="primary"
                size="small"
                disabledReason={!apiKey ? 'API key is required' : undefined}
                onClick={() => installServer({ serverId: server.id, configuration: { api_key: apiKey } })}
            >
                Install
            </LemonButton>
            <LemonButton type="secondary" size="small" onClick={() => setConfiguringServerId(null)}>
                Cancel
            </LemonButton>
        </div>
    )
}

function ConnectButton({ installation }: { installation: MCPServerInstallation }): JSX.Element {
    const [loading, setLoading] = useState(false)

    return (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconPlug />}
            loading={loading}
            onClick={async () => {
                setLoading(true)
                try {
                    const result = await api.mcpServerInstallations.installCustom({
                        name: installation.display_name || installation.name,
                        url: installation.url,
                        auth_type: 'oauth',
                        description: installation.description,
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
    const { installations, installationsLoading, recommendedServers, serversLoading, configuringServerId } =
        useValues(mcpStoreLogic)
    const { installServer, uninstallServer, openAddCustomServerModal, setConfiguringServerId } =
        useActions(mcpStoreLogic)
    const { currentTeamId } = useValues(teamLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="MCP store"
                description="Manage MCP servers for your AI agents."
                resourceType={{ type: 'mcp_store' }}
                actions={
                    <LemonButton type="primary" icon={<IconPlus />} onClick={openAddCustomServerModal} size="small">
                        Add custom server
                    </LemonButton>
                }
            />

            <h3 className="mt-4">Installed servers</h3>
            <LemonTable
                loading={installationsLoading}
                dataSource={installations}
                emptyState="No servers installed yet. Browse recommended servers below or add a custom one."
                columns={[
                    {
                        title: 'Name',
                        render: (_: any, installation: MCPServerInstallation) => (
                            <span className="font-semibold">{installation.name}</span>
                        ),
                    },
                    {
                        title: 'URL',
                        render: (_: any, installation: MCPServerInstallation) => (
                            <span className="text-muted">{installation.url}</span>
                        ),
                    },
                    {
                        title: 'Auth',
                        render: (_: any, installation: MCPServerInstallation) =>
                            installation.pending_oauth ? (
                                <LemonTag type="warning" icon={<IconWarning />}>
                                    Not connected
                                </LemonTag>
                            ) : installation.needs_reauth ? (
                                <LemonTag type="warning" icon={<IconWarning />}>
                                    Needs reconnection
                                </LemonTag>
                            ) : (
                                <LemonTag>{installation.auth_type}</LemonTag>
                            ),
                    },
                    {
                        width: 0,
                        render: (_: any, installation: MCPServerInstallation) => (
                            <div className="flex items-center gap-1">
                                {installation.pending_oauth && <ConnectButton installation={installation} />}
                                {!installation.pending_oauth && installation.needs_reauth && installation.server && (
                                    <LemonButton
                                        type="primary"
                                        size="small"
                                        onClick={() => {
                                            window.location.href = `/api/environments/${currentTeamId}/mcp_server_installations/authorize/?server_id=${installation.server!.id}`
                                        }}
                                    >
                                        Reconnect
                                    </LemonButton>
                                )}
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
                            </div>
                        ),
                    },
                ]}
            />

            {recommendedServers.length > 0 && (
                <>
                    <h3 className="mt-4">Recommended servers</h3>
                    <LemonTable
                        loading={serversLoading}
                        dataSource={recommendedServers}
                        columns={[
                            {
                                title: 'Name',
                                render: (_: any, server: MCPServer) => (
                                    <span className="font-semibold">{server.name}</span>
                                ),
                            },
                            {
                                title: 'Description',
                                render: (_: any, server: MCPServer) => (
                                    <span className="text-muted">{server.description}</span>
                                ),
                            },
                            {
                                title: 'Auth',
                                render: (_: any, server: MCPServer) => <LemonTag>{server.auth_type}</LemonTag>,
                            },
                            {
                                width: 0,
                                render: (_: any, server: MCPServer) =>
                                    configuringServerId === server.id ? null : (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={() => {
                                                if (server.auth_type === 'oauth') {
                                                    window.location.href = `/api/environments/${currentTeamId}/mcp_server_installations/authorize/?server_id=${server.id}`
                                                } else if (server.auth_type === 'api_key') {
                                                    setConfiguringServerId(server.id)
                                                } else {
                                                    installServer({ serverId: server.id })
                                                }
                                            }}
                                        >
                                            {server.auth_type === 'oauth' ? 'Connect' : 'Install'}
                                        </LemonButton>
                                    ),
                            },
                        ]}
                        expandable={{
                            isRowExpanded: (server) => configuringServerId === server.id,
                            expandedRowRender: (server) => <ServerConfigRow server={server} />,
                            noIndent: true,
                        }}
                    />
                </>
            )}

            <AddCustomServerModal />
        </SceneContent>
    )
}

export default scene
