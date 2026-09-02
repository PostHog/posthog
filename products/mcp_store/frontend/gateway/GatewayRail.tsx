import { useActions, useValues } from 'kea'

import { IconGear, IconList, IconPeople, IconPlug } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSkeleton, LemonSnack } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { ServerIcon } from '../scene/icons'
import { GatewayRailStatus, gatewayRailStatus } from './gatewayRailStatus'
import { GatewayServerEntry, mcpGatewayLogic } from './mcpGatewayLogic'
import { GatewayTab, mcpGatewaySceneLogic } from './mcpGatewaySceneLogic'

const MANAGE_LINKS: { tab: GatewayTab; label: string; icon: JSX.Element }[] = [
    { tab: 'servers', label: 'All servers', icon: <IconPlug /> },
    { tab: 'team', label: 'Team & agents', icon: <IconPeople /> },
    { tab: 'settings', label: 'Team settings', icon: <IconGear /> },
    { tab: 'audit', label: 'Audit log', icon: <IconList /> },
]

const STATUS_SUB: Record<Exclude<GatewayRailStatus, 'connected'>, string> = {
    pending_oauth: 'Finishing setup',
    needs_reauth: 'Needs reauth',
    self_disabled: 'Off for you',
    team_off: 'Off for the team',
    revoked: 'Access revoked',
}

const STATUS_DOT_CLASSES: Record<GatewayRailStatus, string> = {
    connected: 'bg-success',
    pending_oauth: 'bg-warning',
    needs_reauth: 'bg-danger',
    self_disabled: 'bg-muted',
    team_off: 'bg-muted',
    revoked: 'bg-muted',
}

export function GatewayRail(): JSX.Element {
    const { connectedServers, serversInitialized, serversLoading } = useValues(mcpGatewayLogic)
    const { activeTab, availableTabs } = useValues(mcpGatewaySceneLogic)
    const { setTab } = useActions(mcpGatewaySceneLogic)

    return (
        <aside className="flex w-60 shrink-0 flex-col gap-1">
            <RailSectionLabel
                label="Your connections"
                count={serversInitialized ? connectedServers.length : undefined}
            />
            {!serversInitialized && serversLoading ? (
                <div className="flex flex-col gap-1 px-2 py-1">
                    <LemonSkeleton className="h-8" repeat={3} />
                </div>
            ) : connectedServers.length === 0 ? (
                <div className="px-2 py-1 text-sm text-secondary">No connections yet.</div>
            ) : (
                connectedServers.map((server) => <RailConnectionRow key={server.id} server={server} />)
            )}

            <LemonDivider className="my-2" />
            <RailSectionLabel label="Manage" />
            {MANAGE_LINKS.filter(({ tab }) => availableTabs.includes(tab)).map(({ tab, label, icon }) => (
                <LemonButton
                    key={tab}
                    fullWidth
                    icon={icon}
                    active={activeTab === tab}
                    onClick={() => setTab(tab)}
                    data-attr={`mcp-gateway-rail-${tab}`}
                >
                    {label}
                </LemonButton>
            ))}
        </aside>
    )
}

function RailConnectionRow({ server }: { server: GatewayServerEntry }): JSX.Element {
    const status = gatewayRailStatus(server) ?? 'connected'
    const lastUsedAt = server.your_connection?.last_used_at
    const sub =
        status === 'connected' ? (lastUsedAt ? `Used ${dayjs(lastUsedAt).fromNow()}` : 'Connected') : STATUS_SUB[status]

    return (
        <LemonButton
            fullWidth
            to={urls.mcpGatewayServer(server.id)}
            icon={<ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={24} />}
            sideIcon={<span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT_CLASSES[status]}`} />}
            tooltip={sub}
            data-attr="mcp-gateway-rail-connection"
        >
            <span className="flex min-w-0 flex-col py-0.5 leading-tight">
                <span className="truncate text-sm font-medium">{server.name}</span>
                <span className="truncate text-xs font-normal text-secondary">{sub}</span>
            </span>
        </LemonButton>
    )
}

function RailSectionLabel({ label, count }: { label: string; count?: number }): JSX.Element {
    return (
        <div className="flex items-center justify-between px-2 pt-1">
            <span className="text-xs font-semibold uppercase tracking-wide text-secondary">{label}</span>
            {count !== undefined && <LemonSnack>{count}</LemonSnack>}
        </div>
    )
}
