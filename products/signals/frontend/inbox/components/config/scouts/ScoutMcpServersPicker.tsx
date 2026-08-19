import { useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronRight, IconServer } from '@posthog/icons'
import { LemonSwitch, LemonTag, LemonTagType, Link, Spinner } from '@posthog/lemon-ui'
import { ServerIcon } from '@posthog/products-mcp-store/frontend/scene/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type { MCPServiceAccountServerApi } from 'products/mcp_store/frontend/generated/api.schemas'

import { scoutMcpServersLogic } from '../../../logics/scoutMcpServersLogic'

/** Rows shown before the list collapses behind "See more". */
const MAX_VISIBLE_SERVERS = 2

interface ScoutMcpServersPickerProps {
    /** Gateway server ids selected for this scout (`mcp_gateway_server_ids`). */
    selectedServerIds: string[]
    onChange: (serverIds: string[]) => void
    /** Compact rows matching the inline scout settings form; the default suits the create dialog. */
    compact?: boolean
    disabledReason?: string
}

/**
 * Per-scout selection among the MCP servers members shared to the whole team, persisted as the
 * scout config's `mcp_gateway_server_ids`. Scouts are a team resource, so only team shares are
 * offered: the selection is the same for every viewer, and matches exactly what the run mounts.
 * Sharing a connection to the team happens on the MCP gateway page, not here.
 */
export function ScoutMcpServersPicker(props: ScoutMcpServersPickerProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.MCP_GATEWAY]) {
        return null
    }
    return props.compact ? <CompactPicker {...props} /> : <FullPicker {...props} />
}

function connectionIssue(server: MCPServiceAccountServerApi): { label: string; tagType: LemonTagType } | null {
    switch (server.connection_state) {
        case 'needs_reauth':
            return { label: 'Reconnect', tagType: 'danger' }
        case 'pending_oauth':
            return { label: 'Pending OAuth', tagType: 'warning' }
        case 'disabled':
            return { label: 'Disabled', tagType: 'muted' }
        case 'missing_credential':
            return { label: 'Needs connection', tagType: 'warning' }
        default:
            return null
    }
}

interface PickerState {
    hiddenCount: number
    initialLoading: boolean
    selectDisabledReason: string | undefined
    showAll: boolean
    setShowAll: (showAll: boolean) => void
    toggleServer: (serverId: string, selected: boolean) => void
    visibleServers: MCPServiceAccountServerApi[]
}

function usePickerState({ selectedServerIds, onChange, disabledReason }: ScoutMcpServersPickerProps): PickerState {
    const [showAll, setShowAll] = useState(false)
    const { scoutAccount, scoutServersLoading, teamScoutServers } = useValues(scoutMcpServersLogic)

    const initialLoading = scoutServersLoading && scoutAccount === null
    const visibleServers = showAll ? teamScoutServers : teamScoutServers.slice(0, MAX_VISIBLE_SERVERS)
    const toggleServer = (serverId: string, selected: boolean): void => {
        onChange(selected ? [...selectedServerIds, serverId] : selectedServerIds.filter((id) => id !== serverId))
    }
    return {
        hiddenCount: teamScoutServers.length - visibleServers.length,
        initialLoading,
        selectDisabledReason:
            disabledReason ??
            (scoutAccount === null && !scoutServersLoading ? 'Scout MCP access is unavailable' : undefined),
        showAll,
        setShowAll,
        toggleServer,
        visibleServers,
    }
}

function SelectSwitch({
    server,
    size,
    state,
    selectedServerIds,
}: {
    server: MCPServiceAccountServerApi
    size?: 'small'
    state: PickerState
    selectedServerIds: string[]
}): JSX.Element {
    return (
        <LemonSwitch
            size={size}
            checked={selectedServerIds.includes(server.id)}
            disabledReason={state.selectDisabledReason}
            onChange={(checked) => state.toggleServer(server.id, checked)}
            aria-label={`Let this scout use ${server.name}`}
        />
    )
}

function FullPicker(props: ScoutMcpServersPickerProps): JSX.Element {
    useMountedLogic(scoutMcpServersLogic)
    const { scoutAccount } = useValues(scoutMcpServersLogic)
    const state = usePickerState(props)

    let body: JSX.Element
    if (state.initialLoading) {
        body = (
            <div className="flex items-center gap-2 rounded border border-dashed px-3 py-4 text-sm text-secondary">
                <Spinner /> Loading MCP servers...
            </div>
        )
    } else if (state.visibleServers.length === 0) {
        body = (
            <div className="flex items-start gap-3 rounded border border-dashed px-3 py-3">
                <IconServer className="size-5 shrink-0 mt-0.5 text-secondary" />
                <div className="min-w-0">
                    <div className="font-medium text-sm text-default">No MCP servers shared with the team yet</div>
                    <p className="text-xs text-secondary mt-0.5 mb-0">
                        <Link to={urls.mcpGateway()}>Share an MCP server with the team</Link> to give scouts external
                        tools.
                    </p>
                </div>
            </div>
        )
    } else {
        body = (
            <div className="rounded border bg-bg-light overflow-hidden">
                <div className="divide-y">
                    {state.visibleServers.map((server) => {
                        const issue = connectionIssue(server)
                        return (
                            <div key={server.id} className="flex items-center gap-3 px-3 py-2.5">
                                <ServerIcon iconDomain={server.icon_domain} size={28} />
                                <div className="min-w-0 flex-1">
                                    <div className="font-medium text-sm text-default truncate">{server.name}</div>
                                    {server.description && (
                                        <div className="text-xs text-secondary truncate">{server.description}</div>
                                    )}
                                </div>
                                {issue && (
                                    <LemonTag type={issue.tagType} size="small">
                                        {issue.label}
                                    </LemonTag>
                                )}
                                <SelectSwitch
                                    server={server}
                                    state={state}
                                    selectedServerIds={props.selectedServerIds}
                                />
                            </div>
                        )
                    })}
                </div>
                {!state.showAll && state.hiddenCount > 0 && (
                    <button
                        type="button"
                        onClick={() => state.setShowAll(true)}
                        className="w-full border-t border-primary px-3 py-2 text-left text-xs text-secondary transition-colors hover:bg-bg-3000 hover:text-default"
                    >
                        See {state.hiddenCount} more
                    </button>
                )}
                {scoutAccount?.status === 'paused' && (
                    <div className="border-t border-primary px-3 py-2 text-xs text-secondary">
                        Scout MCP access is paused.
                    </div>
                )}
                <Link
                    to={urls.mcpGateway()}
                    className="group flex items-center justify-between gap-3 border-t border-primary px-3 py-2 text-xs no-underline transition-colors hover:bg-bg-3000"
                >
                    <span className="text-secondary group-hover:text-default">Share more MCP servers</span>
                    <IconChevronRight className="size-4 shrink-0 text-muted transition-colors group-hover:text-default" />
                </Link>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3 border-t border-primary pt-4">
            <div className="flex flex-col gap-0.5">
                <span className="font-medium text-sm">MCP servers</span>
                <p className="text-xs text-secondary mb-0">
                    Choose which of the team's shared MCP servers this scout can use.
                </p>
            </div>
            {body}
        </div>
    )
}

function CompactPicker(props: ScoutMcpServersPickerProps): JSX.Element {
    useMountedLogic(scoutMcpServersLogic)
    const state = usePickerState(props)

    return (
        <div className="flex flex-col gap-2 border-t border-primary pt-2">
            <div className="flex flex-col min-w-0">
                <span className="text-xs text-default">MCP servers</span>
                <span className="text-[11.5px] text-muted">
                    Choose which of the team's shared MCP servers this scout can use.{' '}
                    <Link to={urls.mcpGateway()}>Manage MCP servers</Link>
                </span>
            </div>
            {state.initialLoading ? (
                <span className="flex items-center gap-2 text-[11.5px] text-muted">
                    <Spinner /> Loading MCP servers...
                </span>
            ) : state.visibleServers.length === 0 ? (
                <span className="text-[11.5px] text-muted">
                    <Link to={urls.mcpGateway()}>Share an MCP server with the team</Link> to give scouts external tools.
                </span>
            ) : (
                <div className="flex flex-col gap-1.5">
                    {state.visibleServers.map((server) => (
                        <div key={server.id} className="flex items-center gap-2">
                            <ServerIcon iconDomain={server.icon_domain} size={20} />
                            <span className="min-w-0 flex-1 truncate text-xs text-default">{server.name}</span>
                            <SelectSwitch
                                server={server}
                                size="small"
                                state={state}
                                selectedServerIds={props.selectedServerIds}
                            />
                        </div>
                    ))}
                    {!state.showAll && state.hiddenCount > 0 && (
                        <button
                            type="button"
                            onClick={() => state.setShowAll(true)}
                            className="w-fit text-left text-[11.5px] text-muted transition-colors hover:text-default"
                        >
                            See {state.hiddenCount} more
                        </button>
                    )}
                </div>
            )}
        </div>
    )
}
