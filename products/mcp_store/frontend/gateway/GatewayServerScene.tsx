import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft, IconExternal, IconLock, IconRefresh, IconTrash, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonDialog,
    LemonDivider,
    LemonInput,
    LemonSegmentedButton,
    LemonTag,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { MCPToolApprovalStateEnumApi, ResolvedToolPolicyApi } from '../generated/api.schemas'
import { ServerIcon } from '../scene/icons'
import { isPolicyStateAllowedByCeiling } from './gatewayPolicyUtils'
import { GatewayRouteGuard } from './GatewayRouteGuard'
import { GatewayAccessSection } from './GatewayServerAccess'
import { GatewayServerLogicProps, gatewayServerLogic, TOOL_PREVIEW_LIMIT } from './gatewayServerLogic'
import { getGatewayServerRemovalAction } from './gatewayServerRemoval'
import { GatewayServersLoadError } from './GatewayServersHome'
import { POLICY_OPTIONS, PolicySummary } from './gatewayUtils'
import { mcpGatewayLogic } from './mcpGatewayLogic'

export const scene: SceneExport<(typeof gatewayServerLogic)['props']> = {
    component: GatewayServerRouteScene,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function GatewayServerRouteScene({ id }: GatewayServerLogicProps): JSX.Element {
    const logicProps: GatewayServerLogicProps = { id }

    return (
        <GatewayRouteGuard>
            <BindLogic logic={gatewayServerLogic} props={logicProps}>
                <GatewayServerScene {...logicProps} />
            </BindLogic>
        </GatewayRouteGuard>
    )
}

export function GatewayServerScene({
    onBack,
}: GatewayServerLogicProps & {
    onBack?: () => void
}): JSX.Element {
    const { server, serverLoading, serversLoadFailed, isAdmin, canManageAgentAccess } = useValues(gatewayServerLogic)
    const { user } = useValues(userLogic)
    const { connectingServerId, disconnectingInstallationIds, removingServerIds, updatingInstallationIds } =
        useValues(mcpGatewayLogic)
    const { connectServer, disconnectServer, loadServers, reconnectServer, removeServer, toggleYourConnectionEnabled } =
        useActions(mcpGatewayLogic)
    const goBack = onBack ?? (() => router.actions.push(urls.mcpGateway()))

    if (!server && serverLoading) {
        return <SceneContent className="mx-auto w-full max-w-[1200px]">Loading…</SceneContent>
    }
    if (!server && serversLoadFailed) {
        return (
            <SceneContent className="mx-auto w-full max-w-[1200px]">
                <LemonButton size="small" type="tertiary" icon={<IconArrowLeft />} onClick={goBack}>
                    Back to servers
                </LemonButton>
                <GatewayServersLoadError serverDetail onRetry={loadServers} />
            </SceneContent>
        )
    }
    if (!server) {
        return <SceneContent className="mx-auto w-full max-w-[1200px]">Server not found.</SceneContent>
    }

    const connection = server.your_connection
    const removalAction = getGatewayServerRemovalAction(server, isAdmin, user?.id)
    const removalPending =
        removingServerIds.has(server.id) ||
        Boolean(connection && disconnectingInstallationIds.has(connection.installation_id))
    const needsReconnect = Boolean(connection?.pending_oauth || connection?.needs_reauth)
    const confirmRemoval = (): void => {
        if (!connection && removalAction !== 'delete_for_everyone') {
            return
        }
        const deletesForEveryone = removalAction === 'delete_for_everyone'
        const deletesForYou = removalAction === 'delete_for_you'
        LemonDialog.open({
            title: deletesForEveryone ? 'Delete MCP server' : deletesForYou ? 'Delete server for you' : 'Disconnect',
            content: deletesForEveryone
                ? `Delete ${server.name} for everyone? This disconnects every teammate and removes the custom server from the team gateway.`
                : deletesForYou
                  ? `Delete ${server.name} for you? This removes its tools without removing the team server for anyone else.`
                  : `Disconnect your ${server.name} account?`,
            primaryButton: {
                children: deletesForEveryone || deletesForYou ? 'Delete' : 'Disconnect',
                status: 'danger',
                onClick: () => {
                    if (deletesForEveryone) {
                        removeServer(server.id)
                    } else if (connection) {
                        disconnectServer(server.id, connection.installation_id, deletesForYou)
                    }
                },
            },
        })
    }

    return (
        <SceneContent className="mx-auto w-full max-w-[1200px]">
            <LemonButton size="small" type="tertiary" icon={<IconArrowLeft />} onClick={goBack}>
                Back to servers
            </LemonButton>

            {serversLoadFailed && <GatewayServersLoadError serverDetail onRetry={loadServers} />}

            <div className="flex items-start gap-3">
                <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={56} />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <h1 className="mb-0 truncate">{server.name}</h1>
                        {isAdmin && !server.is_team_enabled && <LemonTag type="muted">Off</LemonTag>}
                    </div>
                    {server.description && <div className="text-secondary mt-1">{server.description}</div>}
                    <div className="flex items-center gap-3 mt-2 text-xs text-secondary">
                        {server.created_by && (
                            <span>Added by {server.created_by.first_name || server.created_by.email}</span>
                        )}
                        {server.docs_url && (
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                to={server.docs_url}
                                targetBlank
                                icon={<IconExternal />}
                            >
                                Docs
                            </LemonButton>
                        )}
                    </div>
                </div>
                <div className="flex flex-col items-end gap-2 shrink-0">
                    {connection ? (
                        <>
                            <div className="flex items-center gap-2">
                                <span className="text-xs text-secondary">Available to you</span>
                                <LemonSegmentedButton
                                    size="xsmall"
                                    value={connection.is_enabled ? 'on' : 'off'}
                                    options={[
                                        { value: 'on', label: 'On' },
                                        { value: 'off', label: 'Off' },
                                    ]}
                                    disabledReason={
                                        updatingInstallationIds.has(connection.installation_id)
                                            ? 'Updating your connection'
                                            : undefined
                                    }
                                    onChange={(value) =>
                                        toggleYourConnectionEnabled(connection.installation_id, value === 'on')
                                    }
                                />
                            </div>
                            {needsReconnect && (
                                <LemonButton
                                    type="primary"
                                    size="small"
                                    disabledReason={
                                        !server.is_team_enabled
                                            ? 'This server is turned off for the team.'
                                            : server.is_revoked_for_you
                                              ? 'Ask an admin to restore your access first.'
                                              : undefined
                                    }
                                    onClick={() => reconnectServer(connection.installation_id)}
                                >
                                    Reconnect your account
                                </LemonButton>
                            )}
                            {removalAction && (
                                <LemonButton
                                    size="small"
                                    type="tertiary"
                                    status={removalAction === 'disconnect' ? 'default' : 'danger'}
                                    icon={removalAction === 'disconnect' ? <IconX /> : <IconTrash />}
                                    loading={removalPending}
                                    onClick={confirmRemoval}
                                >
                                    {removalAction === 'disconnect' ? 'Disconnect' : 'Delete'}
                                </LemonButton>
                            )}
                        </>
                    ) : (
                        <LemonButton
                            type="primary"
                            size="small"
                            loading={connectingServerId === server.id}
                            disabledReason={
                                server.is_team_enabled ? undefined : 'This server is turned off for the team.'
                            }
                            onClick={() => connectServer(server.id)}
                        >
                            Connect your account
                        </LemonButton>
                    )}
                    {!connection && removalAction === 'delete_for_everyone' && (
                        <LemonButton
                            size="small"
                            type="tertiary"
                            status="danger"
                            icon={<IconTrash />}
                            loading={removalPending}
                            onClick={confirmRemoval}
                        >
                            Delete server
                        </LemonButton>
                    )}
                </div>
            </div>

            {server.is_revoked_for_you && (
                <LemonBanner type="warning">
                    A project admin disabled your access to this server. Ask an admin to restore it.
                </LemonBanner>
            )}
            {connection && !connection.is_enabled && (
                <LemonBanner type="info">
                    This server is off for you. Turn it on to offer its tools to PostHog and your agents.
                </LemonBanner>
            )}

            <LemonDivider />

            {(isAdmin || canManageAgentAccess) && <GatewayAccessSection />}

            <ToolPoliciesSection />
        </SceneContent>
    )
}

function ToolPoliciesSection(): JSX.Element {
    const {
        availableScopes,
        displayedToolPolicies,
        filteredToolPolicies,
        isAdmin,
        canManageAgentAccess,
        policyCounts,
        refreshInstallationId,
        refreshingInstallationIds,
        scope,
        scopeIsResolving,
        toolPolicies,
        toolPoliciesLoading,
        toolSearch,
        toolsExpanded,
    } = useValues(gatewayServerLogic)
    const { setScope, setAllTools, setToolSearch, toggleToolsExpanded } = useActions(gatewayServerLogic)
    const { refreshServerTools } = useActions(mcpGatewayLogic)
    const canEditScope =
        isAdmin || scope.scopeType === 'member' || (scope.scopeType === 'agent' && canManageAgentAccess)
    const agentScope = scope.scopeType === 'agent'
    const bulkOptions = agentScope
        ? POLICY_OPTIONS.filter((option) => option.value !== 'needs_approval')
        : POLICY_OPTIONS
    if (scopeIsResolving) {
        return (
            <div className="border border-dashed rounded p-4 text-sm text-secondary flex items-center gap-2">
                <Spinner /> Loading agent tool policies…
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                    <h3 className="mb-0">Tools</h3>
                    <LemonTag type="muted" size="small">
                        {toolPolicies.length}
                    </LemonTag>
                    <PolicySummary counts={policyCounts} />
                </div>
                <div className="flex items-center gap-2">
                    {canEditScope && (
                        <div className="flex items-center gap-1">
                            <span className="text-xs text-secondary mr-1">
                                {toolSearch.trim() ? 'Set filtered' : 'Set all'}
                            </span>
                            {bulkOptions.map((option) => (
                                <LemonButton
                                    key={option.value}
                                    size="xsmall"
                                    icon={option.icon}
                                    tooltip={option.label}
                                    loading={toolPoliciesLoading}
                                    disabledReason={
                                        filteredToolPolicies.some(
                                            (policy) =>
                                                !policy.locked &&
                                                (scope.scopeType === 'team' ||
                                                    isPolicyStateAllowedByCeiling(option.value, policy.team_state))
                                        )
                                            ? undefined
                                            : 'No editable tools'
                                    }
                                    onClick={() => setAllTools({ state: option.value })}
                                />
                            ))}
                        </div>
                    )}
                    {refreshInstallationId && (
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={<IconRefresh />}
                            tooltip="Refresh tools from server"
                            aria-label="Refresh tools from server"
                            loading={refreshingInstallationIds.has(refreshInstallationId)}
                            onClick={() => refreshServerTools(refreshInstallationId)}
                        />
                    )}
                </div>
            </div>

            {(isAdmin || canManageAgentAccess) && availableScopes.length > 1 && (
                <div className="flex items-center gap-2 flex-wrap rounded border bg-surface-secondary p-2">
                    <span className="text-xs text-secondary">Policy for</span>
                    <LemonSegmentedButton
                        size="small"
                        value={scope.scopeServiceAccountId ?? scope.scopeUserId ?? scope.scopeType}
                        options={availableScopes.map((candidate) => ({
                            value: candidate.scopeServiceAccountId ?? candidate.scopeUserId ?? candidate.scopeType,
                            label: candidate.label,
                        }))}
                        disabledReason={toolPoliciesLoading ? 'Updating tool policies' : undefined}
                        onChange={(value) => {
                            const next = availableScopes.find(
                                (candidate) =>
                                    (candidate.scopeServiceAccountId ??
                                        candidate.scopeUserId ??
                                        candidate.scopeType) === value
                            )
                            if (next) {
                                setScope(next)
                            }
                        }}
                    />
                </div>
            )}

            {toolPolicies.length > 5 && (
                <LemonInput
                    type="search"
                    placeholder="Search tools…"
                    value={toolSearch}
                    onChange={setToolSearch}
                    fullWidth
                    aria-label="Search tools"
                />
            )}

            {toolPoliciesLoading && toolPolicies.length === 0 ? (
                <div className="flex justify-center p-6">
                    <Spinner />
                </div>
            ) : toolPolicies.length === 0 ? (
                <div className="border border-dashed rounded p-6 text-center text-secondary text-sm">
                    <div className="font-semibold text-default">No tools discovered yet.</div>
                    <div className="mt-1">
                        {refreshInstallationId
                            ? 'This server listed no tools. Refresh to try again.'
                            : 'Connect your account to list this server’s tools.'}
                    </div>
                </div>
            ) : filteredToolPolicies.length === 0 ? (
                <div className="border border-dashed rounded p-6 text-center text-secondary text-sm">
                    No tools match “{toolSearch}”.
                </div>
            ) : (
                <div className="border rounded divide-y overflow-hidden bg-surface-primary">
                    {displayedToolPolicies.map((policy) => (
                        <ToolPolicyRow key={policy.tool_name} policy={policy} />
                    ))}
                    {filteredToolPolicies.length > TOOL_PREVIEW_LIMIT && !toolSearch.trim() && (
                        <LemonButton fullWidth type="tertiary" onClick={toggleToolsExpanded}>
                            {toolsExpanded
                                ? 'View less'
                                : `View ${filteredToolPolicies.length - TOOL_PREVIEW_LIMIT} more`}
                        </LemonButton>
                    )}
                </div>
            )}
        </div>
    )
}

function ToolPolicyRow({ policy }: { policy: ResolvedToolPolicyApi }): JSX.Element {
    const { server, scope, isAdmin, canManageAgentAccess, toolPoliciesLoading } = useValues(gatewayServerLogic)
    const { setToolPolicy } = useActions(gatewayServerLogic)

    const fqName = `${server?.name ?? ''}.${policy.tool_name}`
    const ruleLocked = policy.decided_by === 'rule'
    const setByTeamAdmin =
        scope.scopeType !== 'team' && (policy.decided_by === 'team' || policy.decided_by === 'preset')
    const canEditScope =
        isAdmin || scope.scopeType === 'member' || (scope.scopeType === 'agent' && canManageAgentAccess)
    const agentScope = scope.scopeType === 'agent'
    const displayedState: MCPToolApprovalStateEnumApi =
        agentScope && policy.policy_state === 'needs_approval' ? 'do_not_use' : policy.policy_state
    const options = POLICY_OPTIONS.filter((option) => !agentScope || option.value !== 'needs_approval').map(
        (option) => ({
            ...option,
            disabledReason:
                scope.scopeType === 'team' || isPolicyStateAllowedByCeiling(option.value, policy.team_state)
                    ? undefined
                    : 'Unavailable because of the team policy',
        })
    )
    const rulePolicyLabel =
        displayedState === 'do_not_use'
            ? 'Blocked by team policy'
            : displayedState === 'needs_approval'
              ? 'Needs approval by team policy'
              : 'Allowed by team policy'
    const policyControl =
        ruleLocked || !canEditScope ? (
            <Tooltip
                title={
                    ruleLocked
                        ? `${policy.rule_name}: team rule that overrides every scope.`
                        : 'This policy is read-only.'
                }
            >
                <LemonTag icon={<IconLock />} type="muted">
                    {ruleLocked
                        ? rulePolicyLabel
                        : POLICY_OPTIONS.find((option) => option.value === displayedState)?.label}
                </LemonTag>
            </Tooltip>
        ) : (
            <div className="flex items-center gap-2">
                {setByTeamAdmin && (
                    <Tooltip title="This effective state is limited by the team policy.">
                        <LemonTag icon={<IconLock />} type="muted">
                            Set by team admin
                        </LemonTag>
                    </Tooltip>
                )}
                <LemonSegmentedButton
                    size="xsmall"
                    value={displayedState}
                    options={options}
                    disabledReason={
                        toolPoliciesLoading
                            ? 'Updating tool policies'
                            : policy.locked
                              ? 'The team policy blocks this tool.'
                              : undefined
                    }
                    onChange={(value) => setToolPolicy({ toolName: policy.tool_name, state: value })}
                />
            </div>
        )

    return (
        <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
                <LemonCollapse
                    embedded
                    className="[&_.LemonCollapsePanel__header]:!bg-transparent"
                    panels={[
                        {
                            key: policy.tool_name,
                            header: (
                                <div className="min-w-0">
                                    <div
                                        className={`font-mono text-sm ${
                                            displayedState === 'do_not_use' ? 'line-through text-secondary' : ''
                                        }`}
                                    >
                                        {fqName}
                                    </div>
                                    <div className="text-xs text-secondary truncate italic">
                                        {policy.description || 'No description provided'}
                                    </div>
                                </div>
                            ),
                            content: (
                                <div className="text-sm flex flex-col gap-3">
                                    <div>
                                        <div className="text-xs uppercase text-secondary font-semibold mb-1">
                                            Description
                                        </div>
                                        <div>{policy.description || 'No description provided'}</div>
                                    </div>
                                    {ruleLocked && (
                                        <div>
                                            <div className="text-xs uppercase text-secondary font-semibold mb-1">
                                                Applied rule
                                            </div>
                                            <div>
                                                {policy.rule_name}: {policy.rule_description}
                                            </div>
                                        </div>
                                    )}
                                    <div>
                                        <div className="text-xs uppercase text-secondary font-semibold mb-1">
                                            Input schema
                                        </div>
                                        <CodeSnippet language={Language.JSON} wrap>
                                            {JSON.stringify(policy.input_schema, null, 2)}
                                        </CodeSnippet>
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
            <div className="shrink-0 py-2 pr-2">{policyControl}</div>
        </div>
    )
}
