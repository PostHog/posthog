import { useValues } from 'kea'

import { IconServer } from '@posthog/icons'
import { LemonSwitch, LemonTag, Link, Spinner } from '@posthog/lemon-ui'
import { ServerIcon } from '@posthog/products-mcp-store/frontend/scene/icons'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { agentServerConnectionIssue } from 'products/mcp_store/frontend/gateway/agentServerUtils'

import { ServerToolPolicyCounts, taskConnectorsPickerLogic } from './taskConnectorsPickerLogic'

/**
 * Per-step selection among the MCP servers shared with everyone in the project, saved as the
 * "Create AI task" step's `connectors` input (gateway server ids). The run mounts the selection as
 * the workflow agent, so the list is the same for every editor and matches what the run reaches.
 * Sharing a server with the project happens on the MCP servers page, not here.
 */
export default function CyclotronJobInputTaskConnectors(props: CustomInputRendererProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.MCP_GATEWAY]) {
        return (
            <span className="text-xs text-secondary">
                MCP servers for workflow tasks aren't available in this project yet.
            </span>
        )
    }

    // Mount the picker's data logic only inside the enabled branch, so a project outside the rollout
    // never requests the service-account catalog. Mirrors ScoutMcpServersPicker.
    return <TaskConnectorsPicker {...props} />
}

function TaskConnectorsPicker({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const {
        workflowAccount,
        teamWorkflowServers,
        serviceAccountsLoading,
        serviceAccountsFailed,
        toolPolicyCountsByServer,
    } = useValues(taskConnectorsPickerLogic)

    const selectedIds: string[] = Array.isArray(value) ? value : []
    const toggleServer = (serverId: string, selected: boolean): void => {
        onChange(selected ? [...selectedIds, serverId] : selectedIds.filter((id) => id !== serverId))
    }

    // Stored ids with no team share behind them (a server no longer shared with the project, or a
    // selection saved before connectors were keyed by server) stay visible so they can be turned off.
    const unavailableIds = selectedIds.filter((id) => !teamWorkflowServers.some((server) => server.id === id))
    const initialLoading = serviceAccountsLoading && workflowAccount === null

    let body: JSX.Element
    if (initialLoading) {
        body = (
            <div className="flex items-center gap-2 rounded border border-dashed px-3 py-3 text-xs text-secondary">
                <Spinner /> Loading MCP servers...
            </div>
        )
    } else if (serviceAccountsFailed) {
        body = (
            <div className="rounded border border-dashed px-3 py-3 text-xs text-secondary">
                Couldn't load MCP servers. Refresh the page to try again.
            </div>
        )
    } else if (teamWorkflowServers.length === 0 && unavailableIds.length === 0) {
        body = (
            <div className="flex items-start gap-3 rounded border border-dashed px-3 py-3">
                <IconServer className="size-5 shrink-0 mt-0.5 text-secondary" />
                <div className="min-w-0">
                    <div className="font-medium text-sm text-default">No MCP servers shared with the project yet</div>
                    <p className="text-xs text-secondary mt-0.5 mb-0">
                        <Link to={urls.mcpGateway()}>Share an MCP server with everyone in this project</Link> to let
                        this task use it.
                    </p>
                </div>
            </div>
        )
    } else {
        body = (
            <div className="rounded border bg-bg-light overflow-hidden">
                <div className="divide-y">
                    {teamWorkflowServers.map((server) => {
                        const issue = agentServerConnectionIssue(server)
                        const selected = selectedIds.includes(server.id)
                        return (
                            <div key={server.id} className="flex items-center gap-3 px-3 py-3">
                                <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={24} />
                                <div className="min-w-0 flex-1">
                                    <div className="font-medium text-sm text-default truncate">{server.name}</div>
                                    {server.description && (
                                        <div className="text-xs text-secondary truncate">{server.description}</div>
                                    )}
                                    {selected && workflowAccount && (
                                        <ServerToolPolicyNote
                                            counts={toolPolicyCountsByServer[server.id]}
                                            serverId={server.id}
                                            accountId={workflowAccount.id}
                                        />
                                    )}
                                </div>
                                {issue && (
                                    <LemonTag type={issue.tagType} size="small">
                                        {issue.label}
                                    </LemonTag>
                                )}
                                <LemonSwitch
                                    size="small"
                                    checked={selected}
                                    onChange={(checked) => toggleServer(server.id, checked)}
                                    aria-label={`Let this task use ${server.name}`}
                                    data-attr="task-connectors-picker-server"
                                />
                            </div>
                        )
                    })}
                    {unavailableIds.map((id) => (
                        <div key={id} className="flex items-center gap-3 px-3 py-2">
                            <IconServer className="size-6 shrink-0 text-secondary" />
                            <div className="min-w-0 flex-1">
                                <div className="font-medium text-sm text-default truncate">Unavailable connector</div>
                                <div className="text-xs text-secondary truncate">
                                    No longer shared with the project. Turn it off.
                                </div>
                            </div>
                            <LemonSwitch
                                size="small"
                                checked
                                onChange={() => toggleServer(id, false)}
                                aria-label="Remove unavailable connector"
                                data-attr="task-connectors-picker-server"
                            />
                        </div>
                    ))}
                </div>
                {workflowAccount?.status === 'paused' && (
                    <div className="border-t border-primary px-3 py-2 text-xs text-secondary">
                        MCP access for the workflow agent is paused. Selected servers won't be available to the task
                        until an admin resumes it.
                    </div>
                )}
                <Link
                    to={urls.mcpGateway()}
                    className="flex items-center justify-between gap-3 border-t border-primary px-3 py-2 text-xs"
                >
                    Manage MCP servers
                </Link>
            </div>
        )
    }

    return <div data-attr="task-connectors-picker">{body}</div>
}

/** Per-state tool counts under an enabled server, so a selection with no approved tools is visible here. */
function ServerToolPolicyNote({
    counts,
    serverId,
    accountId,
}: {
    counts: ServerToolPolicyCounts | 'error' | undefined
    serverId: string
    accountId: string
}): JSX.Element | null {
    if (counts === undefined) {
        return null
    }
    return (
        <div className="mt-1" data-attr="task-connectors-picker-tool-policy-note">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-secondary">
                {counts === 'error' ? (
                    <span>Couldn't load tool approvals. Refresh the page to try again.</span>
                ) : (
                    <span className="flex flex-wrap items-center gap-x-2.5 gap-y-0.5">
                        <PolicyDot color="bg-success" label={`${counts.approved} always allow`} />
                        {counts.needs_approval > 0 && (
                            <PolicyDot color="bg-warning" label={`${counts.needs_approval} needs approval`} />
                        )}
                        {counts.do_not_use > 0 && (
                            <PolicyDot color="bg-danger" label={`${counts.do_not_use} blocked`} />
                        )}
                    </span>
                )}
                <Link
                    to={urls.mcpGatewayServer(serverId, `agent:${accountId}`)}
                    className="shrink-0"
                    data-attr="task-connectors-picker-tool-policies"
                >
                    Tool policies
                </Link>
            </div>
            {counts !== 'error' && counts.approved === 0 && (
                <div className="mt-0.5 text-xs text-warning">
                    No tools approved yet, so task runs can't use this server.
                </div>
            )}
        </div>
    )
}

function PolicyDot({ color, label }: { color: string; label: string }): JSX.Element {
    return (
        <span className="flex items-center gap-1 whitespace-nowrap">
            <span className={`size-1.5 shrink-0 rounded-full ${color}`} />
            {label}
        </span>
    )
}
