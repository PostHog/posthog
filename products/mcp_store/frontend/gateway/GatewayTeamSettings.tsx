import { MakeLogicType, actions, kea, path, reducers, useActions, useValues } from 'kea'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ServerIcon } from '../scene/icons'
import { GatewayServerEntry, isTemplateOnlyServer, mcpGatewayLogic } from './mcpGatewayLogic'

const SERVER_PREVIEW_LIMIT = 10

interface gatewayTeamSettingsViewLogicValues {
    serverSearch: string
    serversExpanded: boolean
}

interface gatewayTeamSettingsViewLogicActions {
    setServerSearch: (serverSearch: string) => { serverSearch: string }
    toggleServersExpanded: () => { value: true }
}

type gatewayTeamSettingsViewLogicType = MakeLogicType<
    gatewayTeamSettingsViewLogicValues,
    gatewayTeamSettingsViewLogicActions
>

const gatewayTeamSettingsViewLogic = kea<gatewayTeamSettingsViewLogicType>([
    path(['products', 'mcp_store', 'frontend', 'gateway', 'gatewayTeamSettingsViewLogic']),
    actions({
        setServerSearch: (serverSearch: string) => ({ serverSearch }),
        toggleServersExpanded: true,
    }),
    reducers({
        serverSearch: ['', { setServerSearch: (_, { serverSearch }) => serverSearch }],
        serversExpanded: [
            false,
            {
                setServerSearch: () => false,
                toggleServersExpanded: (expanded) => !expanded,
            },
        ],
    }),
])

export interface GatewayTeamSettingsProps {
    onOpenServer?: (id: string) => void
}

export function GatewayTeamSettings({ onOpenServer }: GatewayTeamSettingsProps = {}): JSX.Element {
    const {
        allServersEnabledTarget,
        allowCustomServers,
        allowCustomServersLoading,
        allowMemberAgentAccess,
        allowMemberAgentAccessLoading,
        configLoading,
        configMutationInProgress,
        defaultServersEnabled,
        enabledServerCount,
        mergedServers,
        serverEnabledLoadingIds,
        templateEnabledLoadingIds,
    } = useValues(mcpGatewayLogic)
    const { setAllowCustomServers, setAllowMemberAgentAccess, setAllServersEnabled } = useActions(mcpGatewayLogic)
    const { serverSearch, serversExpanded } = useValues(gatewayTeamSettingsViewLogic)
    const { setServerSearch, toggleServersExpanded } = useActions(gatewayTeamSettingsViewLogic)

    const normalizedServerSearch = serverSearch.trim().toLowerCase()
    const filteredServers = mergedServers
        .filter(
            (server) =>
                !normalizedServerSearch ||
                server.name.toLowerCase().includes(normalizedServerSearch) ||
                server.url.toLowerCase().includes(normalizedServerSearch)
        )
        .sort((first, second) => first.name.localeCompare(second.name, undefined, { sensitivity: 'base' }))
    const displayedServers = serversExpanded ? filteredServers : filteredServers.slice(0, SERVER_PREVIEW_LIMIT)
    const serverUpdateInProgress = serverEnabledLoadingIds.size > 0 || templateEnabledLoadingIds.size > 0
    const teamSettingsMutationInProgress = configMutationInProgress || serverUpdateInProgress
    const configMutationDisabledReason = configLoading
        ? 'Wait for team settings to load'
        : teamSettingsMutationInProgress
          ? 'Wait for the team settings update to finish'
          : undefined
    const bulkServerUpdateDisabledReason = configLoading
        ? 'Wait for team settings to load'
        : teamSettingsMutationInProgress
          ? 'Wait for the team settings update to finish'
          : null
    const enableAllDisabledReason = bulkServerUpdateDisabledReason
        ? bulkServerUpdateDisabledReason
        : defaultServersEnabled && enabledServerCount === mergedServers.length
          ? 'All servers are already enabled'
          : null
    const disableAllDisabledReason = bulkServerUpdateDisabledReason
        ? bulkServerUpdateDisabledReason
        : !defaultServersEnabled && enabledServerCount === 0
          ? 'All servers are already disabled'
          : null

    return (
        <div className="flex flex-col gap-6 min-w-0">
            <div className="flex flex-col gap-1">
                <h2 className="mb-0">Team settings</h2>
                <p className="mb-0 text-secondary">
                    Choose which MCP servers your team can use and who can manage access.
                </p>
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Custom servers</h3>
                <div className="border rounded p-3 flex items-center justify-between gap-3 bg-surface-primary">
                    <div>
                        <div className="font-semibold">Allow custom servers</div>
                        <div className="text-sm text-secondary">
                            Members can add their own MCP servers the same way admins do. Team rules still apply.
                        </div>
                    </div>
                    <LemonSwitch
                        checked={allowCustomServers}
                        loading={allowCustomServersLoading}
                        disabledReason={configMutationDisabledReason}
                        aria-label={`${allowCustomServers ? 'Disable' : 'Enable'} custom MCP servers`}
                        onChange={(allowed) => {
                            if (!teamSettingsMutationInProgress && !configLoading) {
                                setAllowCustomServers(allowed)
                            }
                        }}
                    />
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Agent access</h3>
                <div className="border rounded p-3 flex items-center justify-between gap-3 bg-surface-primary">
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
                        disabledReason={configMutationDisabledReason}
                        aria-label={`${allowMemberAgentAccess ? 'Disable' : 'Enable'} member-managed agent access`}
                        onChange={(allowed) => {
                            if (!teamSettingsMutationInProgress && !configLoading) {
                                setAllowMemberAgentAccess(allowed)
                            }
                        }}
                    />
                </div>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3">
                <div>
                    <div className="flex items-center gap-2">
                        <h3 className="mb-0">Server access</h3>
                        <LemonTag type="muted" size="small">
                            {enabledServerCount} of {mergedServers.length} enabled
                        </LemonTag>
                    </div>
                    <p className="mb-0 mt-1 text-sm text-secondary">
                        Every server is available to the team by default. Disable everything to curate access from zero.
                        Servers added to the catalog later stay off too. You can also disable individual servers.
                    </p>
                </div>

                <div className="flex items-center justify-between gap-2 flex-wrap">
                    <LemonInput
                        type="search"
                        placeholder="Search servers"
                        value={serverSearch}
                        onChange={setServerSearch}
                        size="small"
                        aria-label="Search servers"
                    />
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconCheck />}
                            loading={allServersEnabledTarget === true}
                            disabledReason={enableAllDisabledReason}
                            onClick={() => {
                                if (!teamSettingsMutationInProgress && !configLoading) {
                                    setAllServersEnabled(true)
                                }
                            }}
                        >
                            Enable all
                        </LemonButton>
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconX />}
                            loading={allServersEnabledTarget === false}
                            disabledReason={disableAllDisabledReason}
                            onClick={() => {
                                if (!teamSettingsMutationInProgress && !configLoading) {
                                    setAllServersEnabled(false)
                                }
                            }}
                        >
                            Disable all
                        </LemonButton>
                    </div>
                </div>

                <div className="border rounded divide-y overflow-hidden bg-surface-primary">
                    {displayedServers.map((server) => (
                        <GatewayServerAccessRow key={server.id} server={server} onOpenServer={onOpenServer} />
                    ))}
                    {filteredServers.length === 0 && (
                        <div className="p-3 text-sm text-secondary">
                            {mergedServers.length === 0
                                ? 'No servers are available for this team yet.'
                                : `No servers match “${serverSearch.trim()}”. Clear the search and try again.`}
                        </div>
                    )}
                    {filteredServers.length > SERVER_PREVIEW_LIMIT && (
                        <div className="p-1">
                            <LemonButton type="tertiary" size="small" fullWidth center onClick={toggleServersExpanded}>
                                {serversExpanded
                                    ? 'View less'
                                    : `View ${filteredServers.length - SERVER_PREVIEW_LIMIT} more`}
                            </LemonButton>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

function GatewayServerAccessRow({
    server,
    onOpenServer,
}: {
    server: GatewayServerEntry
    onOpenServer?: (id: string) => void
}): JSX.Element {
    const { configMutationInProgress, serverEnabledLoadingIds, templateEnabledLoadingIds } = useValues(mcpGatewayLogic)
    const { toggleServerEnabled, setTemplateEnabled } = useActions(mcpGatewayLogic)

    // Untouched catalog templates have no registry row yet: toggling one
    // materializes it through set_template_enabled instead of a PATCH.
    const templateOnly = isTemplateOnlyServer(server)
    const rowLoading =
        templateOnly && server.template_id
            ? templateEnabledLoadingIds.has(server.template_id)
            : serverEnabledLoadingIds.has(server.id)
    const serverUpdateInProgress = serverEnabledLoadingIds.size > 0 || templateEnabledLoadingIds.size > 0

    return (
        <div className={`flex items-center gap-3 p-2 ${server.is_team_enabled ? '' : 'opacity-60'}`}>
            {templateOnly ? (
                <div className="flex min-w-0 flex-1 items-center gap-3 px-2 py-1">
                    <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
                    <div className="flex-1 min-w-0">
                        <div className="font-semibold truncate">{server.name}</div>
                        <div className="text-xs text-secondary truncate">{server.description}</div>
                    </div>
                </div>
            ) : (
                <LemonButton
                    type="tertiary"
                    className="min-w-0 flex-1 justify-start"
                    to={onOpenServer ? undefined : urls.mcpGatewayServer(server.id)}
                    onClick={onOpenServer ? () => onOpenServer(server.id) : undefined}
                >
                    <div className="flex min-w-0 items-center gap-3">
                        <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
                        <div className="flex-1 min-w-0 text-left">
                            <div className="font-semibold truncate">{server.name}</div>
                            <div className="text-xs text-secondary truncate">{server.description}</div>
                        </div>
                    </div>
                </LemonButton>
            )}
            <LemonSwitch
                checked={server.is_team_enabled}
                loading={rowLoading}
                disabledReason={
                    configMutationInProgress || serverUpdateInProgress
                        ? 'Wait for the team settings update to finish'
                        : undefined
                }
                aria-label={`${server.is_team_enabled ? 'Turn off' : 'Turn on'} ${server.name} for the team`}
                onChange={(checked) => {
                    if (rowLoading || configMutationInProgress || serverUpdateInProgress) {
                        return
                    }
                    if (templateOnly && server.template_id) {
                        setTemplateEnabled(server.template_id, checked)
                    } else {
                        toggleServerEnabled(server.id, checked)
                    }
                }}
            />
        </div>
    )
}
