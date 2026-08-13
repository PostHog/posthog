import { useMountedLogic, useValues } from 'kea'

import { IconChevronRight, IconServer } from '@posthog/icons'
import { LemonTag, LemonTagType, Link, Spinner } from '@posthog/lemon-ui'
import { ServerIcon } from '@posthog/products-mcp-store/frontend/scene/icons'

import { fullName } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { MCPServiceAccountServerApi } from 'products/mcp_store/frontend/generated/api.schemas'

import { scoutMcpServersLogic } from '../../logics/scoutMcpServersLogic'

const CONNECTION_STATE: Record<
    MCPServiceAccountServerApi['connection_state'],
    { label: string; tagType: LemonTagType }
> = {
    ready: { label: 'Connection ready', tagType: 'success' },
    pending_oauth: { label: 'Pending OAuth', tagType: 'warning' },
    needs_reauth: { label: 'Reconnect', tagType: 'danger' },
    disabled: { label: 'Disabled', tagType: 'muted' },
    missing_credential: { label: 'Needs connection', tagType: 'warning' },
}

export function McpServersSection(): JSX.Element {
    useMountedLogic(scoutMcpServersLogic)
    const { scoutAccount, scoutServersLoading, teammateScoutServers, yourScoutServers } =
        useValues(scoutMcpServersLogic)

    if (scoutServersLoading && scoutAccount === null) {
        return (
            <div className="flex items-center gap-2 rounded border border-dashed px-3 py-4 text-sm text-secondary">
                <Spinner /> Loading Scout MCP servers...
            </div>
        )
    }

    return (
        <div className="rounded border bg-bg-light overflow-hidden">
            {yourScoutServers.length === 0 ? (
                <div className="flex items-start gap-3 px-3 py-3">
                    <IconServer className="size-5 shrink-0 mt-0.5 text-secondary" />
                    <div className="min-w-0">
                        <div className="font-medium text-sm text-default">
                            You have not shared any MCP servers with Scout
                        </div>
                        <p className="text-xs text-secondary mt-0.5 mb-0">
                            Share one of your connections in MCP server settings. Your scouts only use connections you
                            shared yourself.
                        </p>
                    </div>
                </div>
            ) : (
                <div className="divide-y">
                    {yourScoutServers.map((server) => (
                        <ScoutServerRow key={server.id} server={server} />
                    ))}
                </div>
            )}
            {teammateScoutServers.length > 0 && (
                <div className="border-t">
                    <div className="px-3 py-2 text-xs text-secondary">Shared by teammates for their own scouts.</div>
                    <div className="divide-y border-t">
                        {teammateScoutServers.map((server) => (
                            <ScoutServerRow key={`${server.id}-${server.shared_by.id}`} server={server} attributed />
                        ))}
                    </div>
                </div>
            )}
            <Link
                to={urls.settings('mcp-servers')}
                className="group flex items-center justify-between gap-3 border-t px-3 py-2 text-xs no-underline transition-colors hover:bg-bg-3000"
            >
                <span className="text-secondary group-hover:text-default">View MCP server settings</span>
                <IconChevronRight className="size-4 shrink-0 text-muted transition-colors group-hover:text-default" />
            </Link>
            {scoutAccount?.status === 'paused' ? (
                <div className="border-t px-3 py-2 text-xs text-secondary">Scout MCP access is paused.</div>
            ) : null}
        </div>
    )
}

function ScoutServerRow({
    server,
    attributed,
}: {
    server: MCPServiceAccountServerApi
    attributed?: boolean
}): JSX.Element {
    const state = CONNECTION_STATE[server.connection_state]
    const sharedBy = fullName(server.shared_by) || server.shared_by.email
    return (
        <div className="flex items-center gap-3 px-3 py-2.5">
            <ServerIcon iconDomain={server.icon_domain} size={28} />
            <div className="min-w-0 flex-1">
                <div className="font-medium text-sm text-default truncate">{server.name}</div>
                {attributed ? (
                    <div className="text-xs text-secondary truncate">Shared by {sharedBy}</div>
                ) : (
                    server.description && <div className="text-xs text-secondary truncate">{server.description}</div>
                )}
            </div>
            {!attributed && (
                <LemonTag type={state.tagType} size="small">
                    {state.label}
                </LemonTag>
            )}
        </div>
    )
}
