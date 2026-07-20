import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDivider, LemonInput, LemonSwitch } from '@posthog/lemon-ui'

import { MCPPolicyPresetEnumApi } from '../generated/api.schemas'
import { AudienceEnumApi } from '../generated/api.schemas'
import { ServerIcon } from '../scene/icons'
import { mcpGatewayLogic } from './mcpGatewayLogic'

const PRESETS: { value: MCPPolicyPresetEnumApi; label: string; description: string }[] = [
    { value: 'allow', label: 'Allow all', description: 'Every tool auto-approved.' },
    { value: 'user', label: 'Member decides', description: 'Every call asks first.' },
    { value: 'ask', label: 'Ask for destructive', description: 'Destructive tools ask a human, rest auto-approved.' },
    { value: 'block', label: 'Block destructive', description: 'Destructive tools blocked, rest auto-approved.' },
]

export function GatewayTeamSettings(): JSX.Element {
    const { config, servers, allowCustomServers, enabledServerCount } = useValues(mcpGatewayLogic)
    const { setAllowCustomServers, applyPreset, toggleServerEnabled, setAllServersEnabled } =
        useActions(mcpGatewayLogic)
    const [serverSearch, setServerSearch] = useState('')

    const filteredServers = servers.filter((server) =>
        server.name.toLowerCase().includes(serverSearch.trim().toLowerCase())
    )

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
                    <LemonSwitch checked={allowCustomServers} onChange={setAllowCustomServers} />
                </div>
            </div>

            <div className="flex flex-col gap-3">
                <h3 className="mb-0">Policy baselines</h3>
                {(['members', 'agents'] as AudienceEnumApi[]).map((audience) => {
                    const current =
                        audience === 'members' ? config?.member_default_preset : config?.agent_default_preset
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
                        Server access · {enabledServerCount} of {servers.length} enabled
                    </h3>
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="search"
                            placeholder="Search servers…"
                            value={serverSearch}
                            onChange={setServerSearch}
                            size="small"
                        />
                        <LemonButton
                            size="small"
                            disabledReason={enabledServerCount === servers.length ? 'Already enabled' : undefined}
                            onClick={() => setAllServersEnabled(true)}
                        >
                            Enable all
                        </LemonButton>
                        <LemonButton
                            size="small"
                            disabledReason={enabledServerCount === 0 ? 'Already disabled' : undefined}
                            onClick={() => setAllServersEnabled(false)}
                        >
                            Disable all
                        </LemonButton>
                    </div>
                </div>
                <div className="text-sm text-secondary">
                    Everything is shared with the team by default. Disable everything to curate up from zero, or switch
                    off individual servers.
                </div>
                <div className="border rounded divide-y">
                    {filteredServers.map((server) => (
                        <div key={server.id} className="flex items-center gap-3 p-2">
                            <ServerIcon iconKey={server.icon_key || undefined} size={28} />
                            <div className="flex-1">
                                <div className="font-semibold">{server.name}</div>
                                <div className="text-xs text-secondary">
                                    {server.auth_mode === 'shared' ? 'Shared credential' : 'Individual accounts'}
                                </div>
                            </div>
                            <LemonSwitch
                                checked={server.is_team_enabled}
                                onChange={(checked) => toggleServerEnabled(server.id, checked)}
                            />
                        </div>
                    ))}
                    {filteredServers.length === 0 && (
                        <div className="p-3 text-sm text-secondary">No servers match “{serverSearch}”.</div>
                    )}
                </div>
            </div>

            <GatewayRulesSection />
        </div>
    )
}

function GatewayRulesSection(): JSX.Element {
    const { rules, rulesLoading } = useValues(mcpGatewayLogic)
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
                                onChange={(checked) => toggleRuleEnabled(rule.id, checked)}
                            />
                        </div>
                    ))
                )}
            </div>
        </div>
    )
}
