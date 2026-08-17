import { useActions, useValues } from 'kea'

import { IconCheck, IconPlus, IconSparkles, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonModal,
    LemonSegmentedButton,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    ProfilePicture,
    Spinner,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { defaultAgentGrantPolicy, isPolicyStateAllowedByCeiling } from './gatewayPolicyUtils'
import { AgentToolPolicyState, gatewayServerLogic } from './gatewayServerLogic'
import { AGENT_GRANT_SCOPE_OPTIONS, AgentGrantScopeControl, RemoveAllSharesButton, toProfileUser } from './gatewayUtils'
import { agentServerAccessKey, mcpGatewayLogic, memberServerAccessKey } from './mcpGatewayLogic'

const AGENT_POLICY_OPTIONS = [
    { value: 'approved' as const, label: 'Always allow' },
    { value: 'do_not_use' as const, label: 'Blocked' },
]

export function GatewayAccessSection(): JSX.Element | null {
    const { agentShareDisabledReason, server } = useValues(gatewayServerLogic)
    const { openAgentAccessModal } = useActions(gatewayServerLogic)
    const {
        agentServerAccessLoadingKeys,
        allServersEnabledLoading,
        canManageAgentAccess,
        currentUserId,
        isAdmin,
        memberServerAccessLoadingKeys,
        serverEnabledLoadingIds,
    } = useValues(mcpGatewayLogic)
    const { setAgentServerAccess, setMemberServerAccess, toggleServerEnabled } = useActions(mcpGatewayLogic)

    if (!server || (!isAdmin && !canManageAgentAccess)) {
        return null
    }

    const connections = server.connections ?? []
    const yourInstallationId = server.your_connection?.installation_id

    return (
        <div className="flex flex-col gap-3">
            <GatewayAgentAccessModal />
            <h3 className="mb-0">Access</h3>

            {isAdmin && (
                <>
                    <div className="border rounded p-3 flex items-center justify-between gap-3 bg-surface-secondary">
                        <div>
                            <div className="font-semibold">Available to team members</div>
                            <div className="text-sm text-secondary">
                                {server.is_team_enabled
                                    ? `Members can connect their own ${server.name} account.`
                                    : `Members cannot see or call ${server.name} while it is off.`}
                            </div>
                        </div>
                        <LemonSwitch
                            checked={server.is_team_enabled}
                            loading={allServersEnabledLoading || serverEnabledLoadingIds.has(server.id)}
                            aria-label={`${server.is_team_enabled ? 'Turn off' : 'Turn on'} ${server.name} for the team`}
                            onChange={(checked) => toggleServerEnabled(server.id, checked)}
                        />
                    </div>

                    <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs uppercase text-secondary font-semibold">People connected</span>
                        <LemonTag type="muted" size="small">
                            {connections.length}
                        </LemonTag>
                    </div>
                    {connections.length === 0 ? (
                        <div className="border border-dashed rounded p-3 text-sm text-secondary">
                            No one has connected yet.
                        </div>
                    ) : (
                        <div className="border rounded divide-y bg-surface-primary">
                            {connections.map((connection) => {
                                const isYou = connection.installation_id === yourInstallationId
                                const accessRevoked = server.revoked_user_ids.includes(connection.user.id)
                                const loading = memberServerAccessLoadingKeys.has(
                                    memberServerAccessKey(connection.user.id, server.id)
                                )
                                return (
                                    <div
                                        key={connection.installation_id}
                                        className={`flex items-center gap-3 p-2 ${accessRevoked ? 'opacity-60' : ''}`}
                                    >
                                        <ProfilePicture user={toProfileUser(connection.user)} size="sm" />
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2">
                                                <span className="font-semibold truncate">
                                                    {connection.user.first_name || connection.user.email}
                                                </span>
                                                {isYou && (
                                                    <LemonTag type="highlight" size="small">
                                                        You
                                                    </LemonTag>
                                                )}
                                            </div>
                                            <div className="text-xs text-secondary truncate">
                                                {connection.user.email}
                                            </div>
                                        </div>
                                        {!isYou && (
                                            <LemonButton
                                                size="xsmall"
                                                type="tertiary"
                                                status={accessRevoked ? 'default' : 'danger'}
                                                icon={accessRevoked ? <IconCheck /> : <IconX />}
                                                loading={loading}
                                                onClick={() =>
                                                    setMemberServerAccess(connection.user.id, server.id, accessRevoked)
                                                }
                                            >
                                                {accessRevoked ? 'Restore' : 'Revoke'}
                                            </LemonButton>
                                        )}
                                        <ConnectionStatus
                                            pendingOauth={connection.pending_oauth}
                                            needsReauth={connection.needs_reauth}
                                            accessRevoked={accessRevoked}
                                            lastUsedAt={connection.last_used_at}
                                        />
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </>
            )}

            <div className="flex items-center gap-2">
                <span className="text-xs uppercase text-secondary font-semibold">Agents</span>
                <LemonTag type="muted" size="small">
                    {server.agents.length}
                </LemonTag>
                <LemonButton
                    className="ml-auto"
                    size="small"
                    type="tertiary"
                    icon={<IconPlus />}
                    onClick={() => openAgentAccessModal()}
                    disabledReason={agentShareDisabledReason}
                >
                    Share access with an agent
                </LemonButton>
            </div>
            <div className="text-sm text-secondary">
                You share your own {server.name} connection, and each teammate shares theirs. Pick whether an agent uses
                it only for your runs or for every agent run in this project. Teammates can't use the connection
                directly, but agents can act through it on their runs.
            </div>

            {server.agents.length === 0 ? (
                <div className="border border-dashed rounded p-3 text-sm text-secondary">
                    No agents have access. Share your connection and choose which tools the agent may call.
                </div>
            ) : (
                <div className="border rounded divide-y bg-surface-primary">
                    {server.agents.map((agent) => {
                        const sharedByYou = agent.user.id === currentUserId
                        const agentShareCount = server.agents.filter(
                            (candidate) => candidate.service_account_id === agent.service_account_id
                        ).length
                        return (
                            <div
                                key={`${agent.service_account_id}:${agent.user.id}`}
                                className="flex items-center gap-3 p-2"
                            >
                                <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-secondary">
                                    <IconSparkles />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="font-semibold truncate">{agent.name}</div>
                                    <div className="text-xs text-secondary truncate">
                                        <span className="font-mono">{agent.handle}</span>
                                        {sharedByYou
                                            ? ' · shared by you'
                                            : ` · shared ${agent.scope === 'team' ? 'to the team ' : ''}by ${agent.user.first_name || agent.user.email}`}
                                    </div>
                                </div>
                                {sharedByYou && (
                                    <AgentGrantScopeControl
                                        accountId={agent.service_account_id}
                                        serverId={server.id}
                                        scope={agent.scope}
                                    />
                                )}
                                {sharedByYou ? (
                                    <LemonButton
                                        size="xsmall"
                                        type="tertiary"
                                        status="danger"
                                        icon={<IconX />}
                                        loading={agentServerAccessLoadingKeys.has(
                                            agentServerAccessKey(agent.service_account_id, server.id)
                                        )}
                                        onClick={() => setAgentServerAccess(agent.service_account_id, server.id, false)}
                                    >
                                        Revoke
                                    </LemonButton>
                                ) : (
                                    <RemoveAllSharesButton
                                        accountId={agent.service_account_id}
                                        accountName={agent.name}
                                        serverId={server.id}
                                        serverName={server.name}
                                        shareCount={agentShareCount}
                                    />
                                )}
                                <LemonTag type={agent.status === 'active' ? 'success' : 'muted'} size="small">
                                    {agent.status === 'active'
                                        ? agent.last_active_at
                                            ? `Active ${dayjs(agent.last_active_at).fromNow()}`
                                            : 'Active'
                                        : 'Paused'}
                                </LemonTag>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

function ConnectionStatus({
    pendingOauth,
    needsReauth,
    accessRevoked,
    lastUsedAt,
}: {
    pendingOauth: boolean
    needsReauth: boolean
    accessRevoked: boolean
    lastUsedAt: string | null
}): JSX.Element {
    if (accessRevoked) {
        return <LemonTag type="muted">Access revoked</LemonTag>
    }
    if (needsReauth) {
        return <LemonTag type="danger">Needs reauth</LemonTag>
    }
    if (pendingOauth) {
        return <LemonTag type="warning">Finishing setup</LemonTag>
    }
    return <LemonTag type="success">{lastUsedAt ? `Used ${dayjs(lastUsedAt).fromNow()}` : 'Connected'}</LemonTag>
}

function GatewayAgentAccessModal(): JSX.Element | null {
    const {
        agentAccessModalOpen,
        agentAccessPolicyMap,
        agentAccessScope,
        agentAccessSelectedId,
        agentShareDisabledReason,
        agentServerAccessLoadingKeys,
        availableAgentAccounts,
        server,
        teamToolPolicies,
        teamToolPoliciesLoadFailed,
        teamToolPoliciesLoading,
    } = useValues(gatewayServerLogic)
    const {
        closeAgentAccessModal,
        loadTeamToolPolicies,
        setAgentAccessScope,
        setAgentAccessSelectedId,
        setAgentAccessToolPolicy,
        setAllAgentAccessTools,
        submitAgentAccess,
    } = useActions(gatewayServerLogic)

    if (!agentAccessModalOpen || !server) {
        return null
    }

    const submitting = agentAccessSelectedId
        ? agentServerAccessLoadingKeys.has(agentServerAccessKey(agentAccessSelectedId, server.id))
        : false
    return (
        <LemonModal
            isOpen
            onClose={() => {
                if (!submitting) {
                    closeAgentAccessModal()
                }
            }}
            title={`Share ${server.name} with an agent`}
            description="Choose an agent and set its tool access. Agents cannot respond to approval prompts."
            width={680}
            footer={
                <div className="flex justify-end gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={closeAgentAccessModal}
                        disabledReason={submitting ? 'Sharing access' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitAgentAccess}
                        loading={submitting}
                        disabledReason={
                            agentShareDisabledReason ??
                            (agentAccessSelectedId
                                ? teamToolPoliciesLoading
                                    ? 'Loading tools'
                                    : teamToolPoliciesLoadFailed
                                      ? 'Could not load tools. Retry before sharing access.'
                                      : undefined
                                : availableAgentAccounts.length
                                  ? 'Choose an agent'
                                  : 'You already share this server with every available agent')
                        }
                    >
                        Share access
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <LemonSelect
                    aria-label="Agent"
                    value={agentAccessSelectedId}
                    onChange={setAgentAccessSelectedId}
                    placeholder="Choose an agent"
                    options={availableAgentAccounts.map((account) => ({
                        value: account.id,
                        label: `${account.name} (${account.handle})${account.status === 'paused' ? ' (paused)' : ''}`,
                    }))}
                    fullWidth
                />

                {agentAccessSelectedId && (
                    <>
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <div className="font-semibold">Share with</div>
                                <div className="text-sm text-secondary">
                                    A team share lets the agent use your connection for every run in this project.
                                </div>
                            </div>
                            <LemonSegmentedButton
                                size="small"
                                value={agentAccessScope}
                                options={AGENT_GRANT_SCOPE_OPTIONS}
                                onChange={setAgentAccessScope}
                            />
                        </div>

                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <div className="font-semibold">Tool access</div>
                                <div className="text-sm text-secondary">
                                    Destructive tools start blocked. Other tools start allowed.
                                </div>
                            </div>
                            <div className="flex items-center gap-1">
                                <span className="text-xs text-secondary">Set all</span>
                                {AGENT_POLICY_OPTIONS.map((option) => (
                                    <LemonButton
                                        key={option.value}
                                        size="xsmall"
                                        onClick={() => setAllAgentAccessTools(option.value)}
                                        disabledReason={
                                            teamToolPoliciesLoading
                                                ? 'Loading tools'
                                                : teamToolPoliciesLoadFailed
                                                  ? 'Retry loading tools first'
                                                  : teamToolPolicies.some(
                                                          (policy) =>
                                                              policy.decided_by !== 'rule' &&
                                                              isPolicyStateAllowedByCeiling(
                                                                  option.value,
                                                                  policy.team_state
                                                              )
                                                      )
                                                    ? undefined
                                                    : 'No editable tools are available'
                                        }
                                    >
                                        {option.label}
                                    </LemonButton>
                                ))}
                            </div>
                        </div>

                        {teamToolPoliciesLoading ? (
                            <div className="flex items-center gap-2 rounded border border-dashed p-4 text-secondary">
                                <Spinner /> Loading tools…
                            </div>
                        ) : teamToolPoliciesLoadFailed ? (
                            <div className="flex items-center justify-between gap-3 rounded border border-dashed p-4 text-sm text-secondary">
                                <span>Couldn’t load this server’s tools. Try again before sharing access.</span>
                                <LemonButton type="secondary" size="small" onClick={() => loadTeamToolPolicies()}>
                                    Retry
                                </LemonButton>
                            </div>
                        ) : teamToolPolicies.length === 0 ? (
                            <div className="rounded border border-dashed p-4 text-sm text-secondary">
                                No tools have been discovered for this server yet.
                            </div>
                        ) : (
                            <div className="max-h-80 overflow-y-auto rounded border divide-y">
                                {teamToolPolicies.map((policy) => {
                                    const ruleLocked = policy.decided_by === 'rule'
                                    const value =
                                        agentAccessPolicyMap[policy.tool_name] ??
                                        defaultAgentGrantPolicy(
                                            policy.tool_name,
                                            policy.team_state,
                                            policy.is_destructive
                                        )
                                    return (
                                        <div key={policy.tool_name} className="flex items-center gap-3 p-3">
                                            <div className="flex-1 min-w-0">
                                                <div className="font-mono text-sm truncate">{policy.tool_name}</div>
                                                <div className="text-xs text-secondary truncate">
                                                    {policy.description || 'No description provided'}
                                                </div>
                                            </div>
                                            {ruleLocked ? (
                                                <LemonTag type="muted">
                                                    {policy.policy_state === 'approved'
                                                        ? 'Allowed by rule'
                                                        : 'Blocked by rule'}
                                                </LemonTag>
                                            ) : (
                                                <LemonSegmentedButton
                                                    size="xsmall"
                                                    value={value}
                                                    options={AGENT_POLICY_OPTIONS.map((option) => ({
                                                        ...option,
                                                        disabledReason: isPolicyStateAllowedByCeiling(
                                                            option.value,
                                                            policy.team_state
                                                        )
                                                            ? undefined
                                                            : 'Unavailable because of the team policy',
                                                    }))}
                                                    onChange={(state: AgentToolPolicyState) =>
                                                        setAgentAccessToolPolicy(policy.tool_name, state)
                                                    }
                                                />
                                            )}
                                        </div>
                                    )
                                })}
                            </div>
                        )}
                    </>
                )}
            </div>
        </LemonModal>
    )
}
