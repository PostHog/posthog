import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { AddCustomServerModal } from './AddCustomServerModal'
import { MCPServer, MCPServerInstallation, mcpStoreLogic } from './mcpStoreLogic'

export const scene: SceneExport = {
    component: McpStoreScene,
    logic: mcpStoreLogic,
}

export function McpStoreScene(): JSX.Element {
    const { installations, installationsLoading, recommendedServers, serversLoading } = useValues(mcpStoreLogic)
    const { installServer, uninstallServer, openAddCustomServerModal } = useActions(mcpStoreLogic)

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
                            <span className="font-semibold">{installation.server.name}</span>
                        ),
                    },
                    {
                        title: 'URL',
                        render: (_: any, installation: MCPServerInstallation) => (
                            <span className="text-muted">{installation.server.url}</span>
                        ),
                    },
                    {
                        title: 'Auth',
                        render: (_: any, installation: MCPServerInstallation) => (
                            <LemonTag>{installation.server.auth_type}</LemonTag>
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
                                render: (_: any, server: MCPServer) => (
                                    <LemonButton type="secondary" size="small" onClick={() => installServer(server.id)}>
                                        Install
                                    </LemonButton>
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
