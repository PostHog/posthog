import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDivider, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { MCPPolicyPresetEnumApi } from '../generated/api.schemas'
import { AudienceEnumApi } from '../generated/api.schemas'
import { ServerIcon } from '../scene/icons'
import { GatewayServerEntry, isTemplateOnlyServer, mcpGatewayLogic } from './mcpGatewayLogic'

const PRESETS: { value: MCPPolicyPresetEnumApi; label: string; description: string }[] = [
    { value: 'allow', label: 'Allow all', description: 'Every tool is set to Always Allow.' },
    { value: 'user', label: 'Member decides', description: 'Every call asks first.' },
    { value: 'ask', label: 'Ask for destructive', description: 'Destructive tools need approval, rest Always Allow.' },
    { value: 'block', label: 'Block destructive', description: 'Destructive tools are Blocked, rest Always Allow.' },
]

export function GatewayTeamSettings(): JSX.Element {
    const {
        allServersEnabledLoading,
        allowCustomServers,
        allowCustomServersLoading,
        allowMemberAgentAccess,
        allowMemberAgentAccessLoading,
        applyingPresetByAudience,
        config,
        defaultServersEnabled,
        enabledServerCount,
        mergedServers,
        serverEnabledLoadingIds,
        templateEnabledLoadingIds,
    } = useValues(mcpGatewayLogic)
    const { setAllowCustomServers, setAllowMemberAgentAccess, applyPreset, setAllServersEnabled } =
        useActions(mcpGatewayLogic)
    const [serverSearch, setServerSearch] = useState('')

    const filteredServers = mergedServers.filter((server) =>
        server.name.toLowerCase().includes(serverSearch.trim().toLowerCase())
    )
    const presetUpdateInProgress = Object.keys(applyingPresetByAudience).length > 0

    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Custom servers</h3>
                <div className="border rounded p-3 flex items-center justify-between gap-3">
                    <div>
                        <div className="font-semibold">Allow custom servers</div>
                        <div className="text-sm text-secondary">
                            Members can add their own MCP servers, the same way admins do. Team rules and baselines
                            still apply.
                        </div>
                    </div>
                    <LemonSwitch
                        checked={allowCustomServers}
                        loading={allowCustomServersLoading}
                        aria-label={`${allowCustomServers ? 'Disable' : 'Enable'} custom MCP servers`}
                        onChange={setAllowCustomServers}
                    />
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Agent access</h3>
                <div className="border rounded p-3 flex items-center justify-between gap-3">
                    <div>
                        <div className="font-semibold">Allow members to manage agent access</div>
                        <div className="text-sm text-secondary">
                            Members can share connections with PostHog agents and choose which tools those agents may
                            call. Turn this off to make those controls admin-only.
                        </div>
                    </div>
                    <LemonSwitch
                        checked={allowMemberAgentAccess}
                        loading={allowMemberAgentAccessLoading}
                        aria-label={`${allowMemberAgentAccess ? 'Disable' : 'Enable'} member-managed agent access`}
                        onChange={setAllowMemberAgentAccess}
                    />
                </div>
            </div>

            <div className="flex flex-col gap-3">
                <h3 className="mb-0">Policy baselines</h3>
                {(['members', 'agents'] as AudienceEnumApi[]).map((audience) => {
                    const current =
                        audience === 'members' ? config?.member_default_preset : config?.agent_default_preset
                    const applyingPreset = applyingPresetByAudience[audience]
                    return (
                        <div key={audience} className="border rounded p-3 flex flex-col gap-2">
                            <div className="font-semibold capitalize">{audience}</div>
                            <div className="flex gap-2 flex-wrap">
                                {PRESETS.map((preset) => (
                                    <LemonButton
                                        key={preset.value}
                                        size="small"
                                        type={current === preset.value ? 'primary' : 'secondary'}
                                        tooltip={preset.description}
                                        loading={applyingPreset === preset.value}
                                        disabledReason={
                                            presetUpdateInProgress
                                                ? 'Wait for the baseline update to finish'
                                                : undefined
                                        }
                                        onClick={() => applyPreset(audience, preset.value)}
                                    >
                                        {preset.label}
                                    </LemonButton>
                                ))}
                            </div>
                        </div>
                    )
                })}
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                    <h3 className="mb-0">
                        Server access · {enabledServerCount} of {mergedServers.length} enabled
                    </h3>
                    <LemonInput
                        type="search"
                        placeholder="Search servers…"
                        value={serverSearch}
                        onChange={setServerSearch}
                        size="small"
                    />
                </div>
                <div className="border rounded p-3 flex items-center justify-between gap-3">
                    <div>
                        <div className="font-semibold">All servers</div>
                        <div className="text-sm text-secondary">
                            Turning this off disables every server, including catalog servers PostHog adds later.
                            Turning it on enables them all. You can still switch individual servers below.
                        </div>
                    </div>
                    <LemonSwitch
                        checked={defaultServersEnabled}
                        loading={allServersEnabledLoading}
                        disabledReason={
                            serverEnabledLoadingIds.size > 0 || templateEnabledLoadingIds.size > 0
                                ? 'Wait for the server update to finish'
                                : undefined
                        }
                        aria-label={`${defaultServersEnabled ? 'Disable' : 'Enable'} all MCP servers for the team`}
                        onChange={setAllServersEnabled}
                    />
                </div>
                <div className="text-sm text-secondary">
                    Switching a server off blocks members and agents alike. Servers no one has touched follow the "All
                    servers" default above.
                </div>
                <div className="border rounded divide-y">
                    {filteredServers.map((server) => (
                        <GatewayServerAccessRow key={server.id} server={server} />
                    ))}
                    {filteredServers.length === 0 && (
                        <div className="p-3 text-sm text-secondary">
                            {mergedServers.length === 0
                                ? 'No servers configured for this team yet.'
                                : `No servers match “${serverSearch.trim()}”.`}
                        </div>
                    )}
                </div>
            </div>

            <GatewayRulesSection />
        </div>
    )
}

function GatewayServerAccessRow({ server }: { server: GatewayServerEntry }): JSX.Element {
    const { allServersEnabledLoading, serverEnabledLoadingIds, templateEnabledLoadingIds } = useValues(mcpGatewayLogic)
    const { toggleServerEnabled, setTemplateEnabled } = useActions(mcpGatewayLogic)

    // Untouched catalog templates have no registry row yet: toggling one
    // materializes it through set_template_enabled instead of a PATCH.
    const templateOnly = isTemplateOnlyServer(server)
    const loading =
        allServersEnabledLoading ||
        (templateOnly && server.template_id
            ? templateEnabledLoadingIds.has(server.template_id)
            : serverEnabledLoadingIds.has(server.id))

    return (
        <div className="flex items-center gap-3 p-2">
            <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
            <div className="flex-1 min-w-0">
                <div className="font-semibold">{server.name}</div>
                <div className="text-xs text-secondary truncate">{server.url}</div>
            </div>
            <LemonSwitch
                checked={server.is_team_enabled}
                loading={loading}
                aria-label={`${server.is_team_enabled ? 'Turn off' : 'Turn on'} ${server.name} for the team`}
                onChange={(checked) =>
                    templateOnly && server.template_id
                        ? setTemplateEnabled(server.template_id, checked)
                        : toggleServerEnabled(server.id, checked)
                }
            />
        </div>
    )
}

function GatewayRulesSection(): JSX.Element {
    const { ruleEnabledLoadingIds, rules, rulesLoading } = useValues(mcpGatewayLogic)
    const { toggleRuleEnabled } = useActions(mcpGatewayLogic)

    return (
        <div className="flex flex-col gap-2">
            <h3 className="mb-0">Org rules</h3>
            <div className="text-sm text-secondary">
                Guardrails evaluated before any scope policy. A matching enabled rule locks the tool for its audience —
                no scope can loosen it.
            </div>
            <div className="border rounded divide-y">
                {rules.length === 0 && !rulesLoading ? (
                    <div className="p-3 text-sm text-secondary">No org rules yet.</div>
                ) : (
                    rules.map((rule) => (
                        <div key={rule.id} className="flex items-center gap-3 p-3">
                            <div className="flex-1">
                                <div className="font-semibold">{rule.name}</div>
                                <div className="text-xs text-secondary">{rule.description}</div>
                            </div>
                            <LemonSwitch
                                checked={rule.enabled ?? true}
                                loading={ruleEnabledLoadingIds.has(rule.id)}
                                aria-label={`${(rule.enabled ?? true) ? 'Disable' : 'Enable'} ${rule.name}`}
                                onChange={(checked) => toggleRuleEnabled(rule.id, checked)}
                            />
                        </div>
                    ))
                )}
            </div>
        </div>
    )
}
