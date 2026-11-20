import { useActions, useValues } from 'kea'

import { IconCheck, IconX } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Field,
    FieldContent,
    FieldDescription,
    FieldLabel,
    Heading,
    Input,
    Separator,
    Switch,
    Text,
} from '@posthog/quill'

import {
    GatewayTeamSettingsProps,
    SERVER_PREVIEW_LIMIT,
    gatewayTeamSettingsViewLogic,
    gatewayTeamSettingsViewState,
} from './GatewayTeamSettings'
import { mcpGatewayLogic } from './mcpGatewayLogic'
import { QuillGatewayServerAccessRow } from './QuillGatewayServerAccessRow'

export function QuillGatewayTeamSettings({ onOpenServer }: GatewayTeamSettingsProps = {}): JSX.Element {
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

    const {
        filteredServers,
        displayedServers,
        teamSettingsMutationInProgress,
        configMutationDisabledReason,
        enableAllDisabledReason,
        disableAllDisabledReason,
    } = gatewayTeamSettingsViewState({
        configLoading,
        configMutationInProgress,
        defaultServersEnabled,
        enabledServerCount,
        mergedServers,
        serverEnabledLoadingIds,
        templateEnabledLoadingIds,
        serverSearch,
        serversExpanded,
    })
    const canMutate = !teamSettingsMutationInProgress && !configLoading

    return (
        <div className="flex min-w-0 flex-col gap-6">
            <div className="flex flex-col gap-1">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Team settings
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Choose which MCP servers your team can use and who can manage access.
                </Text>
            </div>

            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Custom servers
                </Heading>
                <Card size="sm">
                    <Field orientation="horizontal" className="justify-between gap-3">
                        <FieldContent>
                            <FieldLabel htmlFor="mcp-gateway-allow-custom-servers">Allow custom servers</FieldLabel>
                            <FieldDescription>
                                Members can add their own MCP servers the same way admins do. Team rules still apply.
                            </FieldDescription>
                        </FieldContent>
                        <Switch
                            id="mcp-gateway-allow-custom-servers"
                            checked={allowCustomServers}
                            disabledReason={
                                configMutationDisabledReason ??
                                (allowCustomServersLoading ? 'Saving your change' : undefined)
                            }
                            aria-label={`${allowCustomServers ? 'Disable' : 'Enable'} custom MCP servers`}
                            onCheckedChange={(allowed: boolean) => {
                                if (canMutate) {
                                    setAllowCustomServers(allowed)
                                }
                            }}
                        />
                    </Field>
                </Card>
            </div>

            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Agent access
                </Heading>
                <Card size="sm">
                    <Field orientation="horizontal" className="justify-between gap-3">
                        <FieldContent>
                            <FieldLabel htmlFor="mcp-gateway-allow-member-agent-access">
                                Allow members to manage agent access
                            </FieldLabel>
                            <FieldDescription>
                                Members can share connections with PostHog agents and choose which tools those agents
                                may call. Turn this off to make those controls admin-only.
                            </FieldDescription>
                        </FieldContent>
                        <Switch
                            id="mcp-gateway-allow-member-agent-access"
                            checked={allowMemberAgentAccess}
                            disabledReason={
                                configMutationDisabledReason ??
                                (allowMemberAgentAccessLoading ? 'Saving your change' : undefined)
                            }
                            aria-label={`${allowMemberAgentAccess ? 'Disable' : 'Enable'} member-managed agent access`}
                            onCheckedChange={(allowed: boolean) => {
                                if (canMutate) {
                                    setAllowMemberAgentAccess(allowed)
                                }
                            }}
                        />
                    </Field>
                </Card>
            </div>

            <Separator />

            <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Server access
                        </Heading>
                        <Badge>{`${enabledServerCount} of ${mergedServers.length} enabled`}</Badge>
                    </div>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Every server is available to the team by default. Disable everything to curate access from zero.
                        Servers added to the catalog later stay off too. You can also disable individual servers.
                    </Text>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Input
                        type="search"
                        size="sm"
                        className="w-auto"
                        placeholder="Search servers"
                        value={serverSearch}
                        onChange={(event) => setServerSearch(event.target.value)}
                        aria-label="Search servers"
                    />
                    <div className="flex flex-wrap items-center gap-2">
                        <Button
                            loading={allServersEnabledTarget === true}
                            disabledReason={enableAllDisabledReason}
                            onClick={() => {
                                if (canMutate) {
                                    setAllServersEnabled(true)
                                }
                            }}
                        >
                            <IconCheck />
                            Enable all
                        </Button>
                        <Button
                            loading={allServersEnabledTarget === false}
                            disabledReason={disableAllDisabledReason}
                            onClick={() => {
                                if (canMutate) {
                                    setAllServersEnabled(false)
                                }
                            }}
                        >
                            <IconX />
                            Disable all
                        </Button>
                    </div>
                </div>

                {filteredServers.length === 0 ? (
                    <Empty>
                        <EmptyHeader>
                            <EmptyDescription>
                                {mergedServers.length === 0
                                    ? 'No servers are available for this team yet.'
                                    : `No servers match “${serverSearch.trim()}”. Clear the search and try again.`}
                            </EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                ) : (
                    <Card size="sm" className="divide-y divide-border p-0">
                        {displayedServers.map((server) => (
                            <QuillGatewayServerAccessRow key={server.id} server={server} onOpenServer={onOpenServer} />
                        ))}
                    </Card>
                )}
                {filteredServers.length > SERVER_PREVIEW_LIMIT && (
                    <Button className="w-full" onClick={toggleServersExpanded}>
                        {serversExpanded ? 'View less' : `View ${filteredServers.length - SERVER_PREVIEW_LIMIT} more`}
                    </Button>
                )}
            </div>
        </div>
    )
}
