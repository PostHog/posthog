import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconLock } from '@posthog/icons'
import { LemonButton, LemonCollapse, LemonDivider, LemonSegmentedButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ResolvedToolPolicyApi } from '../generated/api.schemas'
import { ServerIcon } from '../scene/icons'
import { GatewayAccessSection } from './GatewayServerAccess'
import { gatewayServerLogic } from './gatewayServerLogic'
import { POLICY_OPTIONS, PolicySummary } from './gatewayUtils'

export const scene: SceneExport<(typeof gatewayServerLogic)['props']> = {
    component: GatewayServerScene,
    logic: gatewayServerLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function GatewayServerScene(): JSX.Element {
    const { server, serverLoading, isAdmin } = useValues(gatewayServerLogic)

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
                <ServerIcon iconKey={server.icon_key || undefined} size={52} />
                <div className="flex-1">
                    <div className="flex items-center gap-2">
                        <h1 className="mb-0">{server.name}</h1>
                        {isAdmin && server.auth_mode === 'shared' && <LemonTag type="muted">🔑 Shared credential</LemonTag>}
                        {isAdmin && !server.is_team_enabled && <LemonTag type="muted">Off</LemonTag>}
                    </div>
                    <div className="text-secondary">{server.description || server.url}</div>
                </div>
            </div>

            <LemonDivider />

            {isAdmin && <GatewayAccessSection />}

            <ToolPoliciesSection />
        </SceneContent>
    )
}

function ToolPoliciesSection(): JSX.Element {
    const { toolPolicies, toolPoliciesLoading, policyCounts, scope, availableScopes, isAdmin } =
        useValues(gatewayServerLogic)
    const { setScope, setAllTools } = useActions(gatewayServerLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                    <h3 className="mb-0">Tool policies</h3>
                    <PolicySummary counts={policyCounts} />
                </div>
                <div className="flex items-center gap-1">
                    <span className="text-xs text-secondary mr-1">Set all</span>
                    {POLICY_OPTIONS.map((option) => (
                        <LemonButton
                            key={option.value}
                            size="xsmall"
                            icon={option.icon}
                            tooltip={option.label}
                            onClick={() => setAllTools(option.value)}
                        />
                    ))}
                </div>
            </div>

            {isAdmin && availableScopes.length > 1 && (
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
    const { server } = useValues(gatewayServerLogic)
    const { setToolPolicy } = useActions(gatewayServerLogic)

    const fqName = `${server?.name ?? ''}.${policy.tool_name}`
    const ruleLocked = policy.decided_by === 'rule'

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
                                {policy.locked ? (
                                    <Tooltip
                                        title={
                                            ruleLocked
                                                ? `${policy.rule_name} — team rule, overrides every scope.`
                                                : 'Set by your admin — ask an admin to change it.'
                                        }
                                    >
                                        <LemonTag icon={<IconLock />} type="muted">
                                            {policy.policy_state === 'do_not_use'
                                                ? ruleLocked
                                                    ? 'Blocked by team policy'
                                                    : 'Blocked'
                                                : 'Approval required'}
                                        </LemonTag>
                                    </Tooltip>
                                ) : (
                                    <LemonSegmentedButton
                                        size="xsmall"
                                        value={policy.policy_state}
                                        options={POLICY_OPTIONS}
                                        onChange={(value) => setToolPolicy(policy.tool_name, value)}
                                    />
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
