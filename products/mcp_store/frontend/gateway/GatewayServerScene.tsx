import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconLock } from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDivider,
    LemonSegmentedButton,
    LemonTag,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ResolvedToolPolicyApi } from '../generated/api.schemas'
import { ServerIcon } from '../scene/icons'
import { isPolicyStateAllowedByCeiling } from './gatewayPolicyUtils'
import { GatewayAccessSection } from './GatewayServerAccess'
import { gatewayServerLogic } from './gatewayServerLogic'
import { POLICY_OPTIONS, PolicySummary } from './gatewayUtils'

export const scene: SceneExport<(typeof gatewayServerLogic)['props']> = {
    component: GatewayServerScene,
    logic: gatewayServerLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function GatewayServerScene(): JSX.Element {
    const { server, serverLoading, isAdmin, canManageAgentAccess } = useValues(gatewayServerLogic)

    if (!server && serverLoading) {
        return <SceneContent>Loading…</SceneContent>
    }
    if (!server) {
        return <SceneContent>Server not found.</SceneContent>
    }

    return (
        <SceneContent>
            <LemonButton size="small" onClick={() => router.actions.push(urls.mcpGateway())}>
                ‹ Back to servers
            </LemonButton>

            <div className="flex items-center gap-3">
                <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={52} />
                <div className="flex-1">
                    <div className="flex items-center gap-2">
                        <h1 className="mb-0">{server.name}</h1>
                        {isAdmin && server.auth_mode === 'shared' && (
                            <LemonTag type="muted">🔑 Shared credential</LemonTag>
                        )}
                        {isAdmin && !server.is_team_enabled && <LemonTag type="muted">Off</LemonTag>}
                    </div>
                    <div className="text-secondary">{server.description || server.url}</div>
                </div>
            </div>

            <LemonDivider />

            {canManageAgentAccess && <GatewayAccessSection />}

            <ToolPoliciesSection />
        </SceneContent>
    )
}

function ToolPoliciesSection(): JSX.Element {
    const {
        toolPolicies,
        toolPoliciesLoading,
        policyCounts,
        scope,
        scopeIsResolving,
        availableScopes,
        isAdmin,
        canManageAgentAccess,
    } = useValues(gatewayServerLogic)
    const { setScope, setAllTools } = useActions(gatewayServerLogic)
    const canEditScope =
        isAdmin || scope.scopeType === 'member' || (scope.scopeType === 'agent' && canManageAgentAccess)
    const policyOptions =
        scope.scopeType === 'agent'
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
                    <h3 className="mb-0">Tool policies</h3>
                    <PolicySummary counts={policyCounts} />
                </div>
                {canEditScope && (
                    <div className="flex items-center gap-1">
                        <span className="text-xs text-secondary mr-1">Set all</span>
                        {policyOptions.map((option) => (
                            <LemonButton
                                key={option.value}
                                size="xsmall"
                                icon={option.icon}
                                tooltip={option.label}
                                onClick={() => setAllTools(option.value)}
                            />
                        ))}
                    </div>
                )}
            </div>

            {canManageAgentAccess && availableScopes.length > 1 && (
                <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs text-secondary">Policy for</span>
                    <LemonSegmentedButton
                        size="small"
                        value={scope.scopeServiceAccountId ?? scope.scopeType}
                        options={availableScopes.map((candidate) => ({
                            value: candidate.scopeServiceAccountId ?? candidate.scopeType,
                            label: candidate.label,
                        }))}
                        onChange={(value) => {
                            const next = availableScopes.find(
                                (candidate) => (candidate.scopeServiceAccountId ?? candidate.scopeType) === value
                            )
                            if (next) {
                                setScope(next)
                            }
                        }}
                    />
                </div>
            )}

            {toolPolicies.length === 0 && !toolPoliciesLoading ? (
                <div className="border border-dashed rounded p-6 text-center text-secondary text-sm">
                    No tools discovered yet. Connect the server and refresh its tools.
                </div>
            ) : (
                <div className="border rounded divide-y">
                    {toolPolicies.map((policy) => (
                        <ToolPolicyRow key={policy.tool_name} policy={policy} />
                    ))}
                </div>
            )}
        </div>
    )
}

function ToolPolicyRow({ policy }: { policy: ResolvedToolPolicyApi }): JSX.Element {
    const { server, scope, isAdmin, canManageAgentAccess } = useValues(gatewayServerLogic)
    const { setToolPolicy } = useActions(gatewayServerLogic)

    const fqName = `${server?.name ?? ''}.${policy.tool_name}`
    const ruleLocked = policy.decided_by === 'rule'
    const setByTeamAdmin =
        scope.scopeType !== 'team' && (policy.decided_by === 'team' || policy.decided_by === 'preset')
    const canEditScope =
        isAdmin || scope.scopeType === 'member' || (scope.scopeType === 'agent' && canManageAgentAccess)
    const options = POLICY_OPTIONS.filter(
        (option) => scope.scopeType !== 'agent' || option.value !== 'needs_approval'
    ).map((option) => ({
        ...option,
        disabledReason:
            scope.scopeType === 'team' || isPolicyStateAllowedByCeiling(option.value, policy.team_state)
                ? undefined
                : 'Unavailable because of the team admin ceiling',
    }))

    return (
        <LemonCollapse
            embedded
            panels={[
                {
                    key: policy.tool_name,
                    header: (
                        <div className="flex items-center justify-between gap-3 w-full pr-2">
                            <div className="min-w-0">
                                <div
                                    className={`font-mono text-sm ${
                                        policy.policy_state === 'do_not_use' ? 'line-through text-secondary' : ''
                                    }`}
                                >
                                    {fqName}
                                </div>
                                <div className="text-xs text-secondary truncate italic">
                                    {policy.description || 'No description provided'}
                                </div>
                            </div>
                            <div
                                className="shrink-0"
                                onClick={(e) => e.stopPropagation()}
                                onKeyDown={(e) => e.stopPropagation()}
                                role="presentation"
                            >
                                {ruleLocked || !canEditScope ? (
                                    <Tooltip
                                        title={
                                            ruleLocked
                                                ? `${policy.rule_name} — team rule, overrides every scope.`
                                                : 'This policy is read-only.'
                                        }
                                    >
                                        <LemonTag icon={<IconLock />} type="muted">
                                            {ruleLocked
                                                ? policy.policy_state === 'do_not_use'
                                                    ? 'Blocked by team policy'
                                                    : 'Needs Approval by team policy'
                                                : POLICY_OPTIONS.find((option) => option.value === policy.policy_state)
                                                      ?.label}
                                        </LemonTag>
                                    </Tooltip>
                                ) : (
                                    <div className="flex items-center gap-2">
                                        {setByTeamAdmin && (
                                            <Tooltip title="This effective state is capped by the team admin ceiling.">
                                                <LemonTag icon={<IconLock />} type="muted">
                                                    Set by team admin
                                                </LemonTag>
                                            </Tooltip>
                                        )}
                                        <LemonSegmentedButton
                                            size="xsmall"
                                            value={policy.policy_state}
                                            options={options}
                                            disabledReason={
                                                policy.locked ? 'The team admin ceiling is Blocked.' : undefined
                                            }
                                            onChange={(value) => setToolPolicy(policy.tool_name, value)}
                                        />
                                    </div>
                                )}
                            </div>
                        </div>
                    ),
                    content: (
                        <div className="text-sm flex flex-col gap-2">
                            <div>
                                <div className="text-xs uppercase text-secondary font-semibold">Description</div>
                                <div className="italic">{policy.description || 'No description provided'}</div>
                            </div>
                            {ruleLocked && (
                                <div>
                                    <div className="text-xs uppercase text-secondary font-semibold">Applied rule</div>
                                    <div>
                                        {policy.rule_name} — {policy.rule_description}
                                    </div>
                                </div>
                            )}
                        </div>
                    ),
                },
            ]}
        />
    )
}
