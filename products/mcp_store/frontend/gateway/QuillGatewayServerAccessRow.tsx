import { useActions, useValues } from 'kea'

import { Switch, Text, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ServerIcon } from '../scene/icons'
import { gatewayServerAccessRowState, setGatewayServerTeamEnabled } from './GatewayTeamSettings'
import { GatewayServerEntry, mcpGatewayLogic } from './mcpGatewayLogic'

const ROW_LINK_CLASS =
    'flex min-w-48 flex-1 items-center gap-3 px-3 py-2 text-left hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'

export function QuillGatewayServerAccessRow({
    server,
    onOpenServer,
}: {
    server: GatewayServerEntry
    onOpenServer?: (id: string) => void
}): JSX.Element {
    const { configMutationInProgress, serverEnabledLoadingIds, templateEnabledLoadingIds } = useValues(mcpGatewayLogic)
    const { toggleServerEnabled, setTemplateEnabled } = useActions(mcpGatewayLogic)

    const { templateOnly, rowLoading, serverUpdateInProgress } = gatewayServerAccessRowState(
        server,
        serverEnabledLoadingIds,
        templateEnabledLoadingIds
    )

    const summary = (
        <>
            <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <Text size="xs" weight="medium" className="m-0 truncate" render={<span />}>
                    {server.name}
                </Text>
                <Text size="xs" variant="muted" className="m-0 truncate" render={<span />}>
                    {server.description}
                </Text>
            </span>
        </>
    )

    return (
        <div className={cn('flex flex-wrap items-center gap-2 pr-3', !server.is_team_enabled && 'opacity-60')}>
            {templateOnly ? (
                <div className="flex min-w-48 flex-1 items-center gap-3 px-3 py-2">{summary}</div>
            ) : onOpenServer ? (
                <button type="button" className={ROW_LINK_CLASS} onClick={() => onOpenServer(server.id)}>
                    {summary}
                </button>
            ) : (
                <LinkPrimitive to={urls.mcpGatewayServer(server.id)} className={ROW_LINK_CLASS}>
                    {summary}
                </LinkPrimitive>
            )}
            <Switch
                checked={server.is_team_enabled}
                disabledReason={
                    configMutationInProgress || serverUpdateInProgress
                        ? 'Wait for the team settings update to finish'
                        : undefined
                }
                aria-label={`${server.is_team_enabled ? 'Turn off' : 'Turn on'} ${server.name} for the team`}
                onCheckedChange={(checked: boolean) => {
                    if (rowLoading || configMutationInProgress || serverUpdateInProgress) {
                        return
                    }

                    setGatewayServerTeamEnabled(server, templateOnly, checked, setTemplateEnabled, toggleServerEnabled)
                }}
            />
        </div>
    )
}
