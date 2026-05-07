import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconCheck, IconChevronLeft, IconRefresh, IconShieldLock, IconTrash, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSnack, LemonSwitch, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'

import type {
    MCPServerInstallationApi,
    MCPServerInstallationToolApi,
    MCPServerTemplateApi,
} from '../generated/api.schemas'
import { type ToolApprovalState, mcpStoreLogic } from '../mcpStoreLogic'
import { ServerIcon } from './icons'
import { ToolRow } from './ToolRow'

function authorizeUrl(teamId: number | null, installationId: string): string {
    return `/api/environments/${teamId}/mcp_server_installations/authorize/?installation_id=${installationId}`
}

function countBy<T>(items: T[], predicate: (item: T) => boolean): number {
    return items.filter(predicate).length
}

function PendingOAuthView({ installation }: { installation: MCPServerInstallationApi }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { uninstallServer } = useActions(mcpStoreLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })

    return (
        <div className="border border-dashed border-primary rounded p-6 text-center deprecated-space-y-3">
            <h3 className="mb-0">Finish connecting</h3>
            <p className="text-secondary mb-0">
                This server hasn't completed its OAuth handshake yet. Click below to continue.
            </p>
            <div className="flex items-center justify-center gap-2">
                <LemonButton
                    type="primary"
                    onClick={() => {
                        window.location.href = authorizeUrl(currentTeamId, installation.id)
                    }}
                    disabledReason={restrictedReason}
                >
                    Continue OAuth
                </LemonButton>
                <LemonButton
                    type="secondary"
                    status="danger"
                    icon={<IconTrash />}
                    onClick={() => uninstallServer(installation.id)}
                    disabledReason={restrictedReason}
                >
                    Cancel install
                </LemonButton>
            </div>
        </div>
    )
}

interface ToolsSectionProps {
    installation: MCPServerInstallationApi
    disabledReason: string | null
}

function ToolsSection({ installation, disabledReason }: ToolsSectionProps): JSX.Element {
    const { installationTools, installationToolsLoading } = useValues(mcpStoreLogic)
    const { loadInstallationTools, refreshInstallationTools, setToolApprovalState, setBulkApprovalState } =
        useActions(mcpStoreLogic)
    const [showRemoved, setShowRemoved] = useState(false)

    useEffect(() => {
        if (!installationTools[installation.id]) {
            loadInstallationTools({ installationId: installation.id })
        }
    }, [installation.id, installationTools, loadInstallationTools])

    const tools: MCPServerInstallationToolApi[] = installationTools[installation.id] ?? []
    const visibleTools = useMemo(() => tools.filter((t) => showRemoved || !t.removed_at), [tools, showRemoved])
    const removedCount = countBy(tools, (t) => !!t.removed_at)
    const approvedCount = countBy(tools, (t) => t.approval_state === 'approved')
    const pendingCount = countBy(tools, (t) => (t.approval_state ?? 'needs_approval') === 'needs_approval')
    const blockedCount = countBy(tools, (t) => t.approval_state === 'do_not_use')

    return (
        <div className="deprecated-space-y-3">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                    <h3 className="mb-0">Tools</h3>
                    <LemonSnack>{tools.length}</LemonSnack>
                </div>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={() => refreshInstallationTools({ installationId: installation.id })}
                    loading={installationToolsLoading}
                    disabledReason={disabledReason}
                >
                    Refresh tools
                </LemonButton>
            </div>

            {tools.length > 0 && (
                <div className="flex items-center justify-between gap-2 flex-wrap bg-surface-secondary rounded p-2">
                    <div className="text-xs text-secondary">
                        <span className="font-semibold">{approvedCount}</span> approved ·{' '}
                        <span className="font-semibold">{pendingCount}</span> require approval ·{' '}
                        <span className="font-semibold">{blockedCount}</span> blocked
                    </div>
                    <div className="flex items-center gap-1">
                        <span className="text-xs text-secondary mr-1">Set all:</span>
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={<IconCheck />}
                            onClick={() =>
                                setBulkApprovalState({
                                    installationId: installation.id,
                                    approvalState: 'approved',
                                })
                            }
                            disabledReason={disabledReason}
                        >
                            Approve
                        </LemonButton>
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={<IconShieldLock />}
                            onClick={() =>
                                setBulkApprovalState({
                                    installationId: installation.id,
                                    approvalState: 'needs_approval',
                                })
                            }
                            disabledReason={disabledReason}
                        >
                            Require approval
                        </LemonButton>
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            status="danger"
                            icon={<IconX />}
                            onClick={() =>
                                setBulkApprovalState({
                                    installationId: installation.id,
                                    approvalState: 'do_not_use',
                                })
                            }
                            disabledReason={disabledReason}
                        >
                            Block
                        </LemonButton>
                    </div>
                </div>
            )}

            {removedCount > 0 && (
                <div className="text-xs">
                    <LemonButton size="xsmall" type="tertiary" onClick={() => setShowRemoved((v) => !v)}>
                        {showRemoved ? `Hide ${removedCount} removed` : `Show ${removedCount} removed`}
                    </LemonButton>
                </div>
            )}

            {visibleTools.length === 0 ? (
                <div className="text-center py-8 text-secondary text-sm border border-dashed border-primary rounded">
                    {installationToolsLoading
                        ? 'Loading tools…'
                        : 'No tools reported yet. Click "Refresh tools" after connecting.'}
                </div>
            ) : (
                <div className="border border-primary rounded overflow-hidden">
                    {visibleTools.map((tool) => (
                        <ToolRow
                            key={tool.id}
                            tool={tool}
                            disabledReason={disabledReason}
                            onPolicyChange={(state: ToolApprovalState) =>
                                setToolApprovalState({
                                    installationId: installation.id,
                                    toolName: tool.tool_name,
                                    approvalState: state,
                                })
                            }
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

interface Props {
    installation: MCPServerInstallationApi | null
    template: MCPServerTemplateApi | null
}

export function ServerDetailPanel({ installation, template }: Props): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { selectServer, setSceneView, toggleServerEnabled, uninstallServer, installTemplate } =
        useActions(mcpStoreLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })

    if (!installation && !template) {
        return (
            <div className="text-center py-12">
                <p className="text-secondary">This server could not be found.</p>
                <LemonButton type="secondary" onClick={() => setSceneView('marketplace')}>
                    Back to marketplace
                </LemonButton>
            </div>
        )
    }

    const name = installation?.name ?? template?.name ?? ''
    const description = installation?.description ?? template?.description ?? ''
    const docsUrl = template?.docs_url ?? ''
    const iconKey = installation?.icon_key ?? template?.icon_key ?? null
    const authType = installation?.auth_type ?? template?.auth_type

    const goBack = (): void => {
        selectServer(null)
        setSceneView('marketplace')
    }

    return (
        <div className="deprecated-space-y-6">
            <LemonButton type="tertiary" icon={<IconChevronLeft />} onClick={goBack} size="small">
                Back to marketplace
            </LemonButton>

            <div className="flex gap-4 items-center">
                <ServerIcon iconKey={iconKey} size={56} />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                        <h1 className="mb-0">{name}</h1>
                        {installation && !installation.pending_oauth && !installation.needs_reauth && (
                            <LemonTag type="success">Connected</LemonTag>
                        )}
                        {installation?.needs_reauth && <LemonTag type="danger">Reconnect required</LemonTag>}
                        {installation?.pending_oauth && <LemonTag type="warning">Pending OAuth</LemonTag>}
                        {authType && <LemonSnack>{authType === 'oauth' ? 'OAuth' : 'API key'}</LemonSnack>}
                    </div>
                    {description && <p className="text-secondary mt-2 mb-0">{description}</p>}
                    {docsUrl && (
                        <Link to={docsUrl} target="_blank" className="text-xs mt-1 inline-block">
                            View documentation
                        </Link>
                    )}
                </div>
                <div className="flex items-end gap-3 flex-col">
                    {!installation && template ? (
                        <LemonButton
                            type="primary"
                            onClick={() => installTemplate({ templateId: template.id })}
                            disabledReason={restrictedReason}
                        >
                            Connect
                        </LemonButton>
                    ) : installation?.needs_reauth ? (
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                window.location.href = authorizeUrl(currentTeamId, installation.id)
                            }}
                            disabledReason={restrictedReason}
                        >
                            Reconnect
                        </LemonButton>
                    ) : null}
                    {installation && !installation.pending_oauth && !installation.needs_reauth && (
                        <Tooltip title="Disable to stop the agent from using this server. Tools stay configured.">
                            <LemonSwitch
                                checked={installation.is_enabled !== false}
                                onChange={(checked) => toggleServerEnabled({ id: installation.id, enabled: checked })}
                                disabledReason={restrictedReason ?? undefined}
                            />
                        </Tooltip>
                    )}
                    {installation && (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            size="small"
                            icon={<IconTrash />}
                            onClick={() => uninstallServer(installation.id)}
                            disabledReason={restrictedReason}
                        >
                            Remove
                        </LemonButton>
                    )}
                </div>
            </div>

            <LemonDivider />

            {installation?.pending_oauth ? (
                <PendingOAuthView installation={installation} />
            ) : installation ? (
                <ToolsSection installation={installation} disabledReason={restrictedReason} />
            ) : (
                <div className="border border-dashed border-primary rounded p-6 text-center text-secondary">
                    Connect this server to manage its tools and permissions.
                </div>
            )}
        </div>
    )
}
