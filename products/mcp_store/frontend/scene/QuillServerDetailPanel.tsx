import { useActions, useValues } from 'kea'
import { type ReactNode, useId } from 'react'

import { IconChevronLeft, IconInfo, IconShare, IconTrash } from '@posthog/icons'
import {
    Badge,
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    Field,
    FieldLabel,
    Heading,
    Separator,
    Switch,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { MCPServerInstallationApi, MCPServerTemplateApi } from '../generated/api.schemas'
import { mcpStoreLogic } from '../mcpStoreLogic'
import { ServerIcon } from './icons'

const ENABLE_HELP = 'Disable to stop the agent from using this server. Tools stay configured.'

export function QuillServerDetailPanel({
    installation,
    template,
    isOwner,
    isAdmin,
    restrictedReason,
    mutationDisabledReason,
    removeDisabledReason,
    onBack,
    onShare,
    onContinueOAuth,
    children,
}: {
    installation: MCPServerInstallationApi | null
    template: MCPServerTemplateApi | null
    isOwner: boolean
    isAdmin: boolean
    restrictedReason: string | null
    mutationDisabledReason: string | null
    removeDisabledReason: string | null
    onBack: () => void
    onShare: (installation: MCPServerInstallationApi) => void
    onContinueOAuth: (installationId: string) => void
    /** The tools or the pending OAuth step, shown under the header once a server is installed. */
    children: ReactNode
}): JSX.Element {
    const { installationsLoading } = useValues(mcpStoreLogic)
    const { setSceneView, toggleServerEnabled, uninstallServer, installTemplate, unshareInstallation } =
        useActions(mcpStoreLogic)
    const enabledSwitchId = useId()

    if (!installation && !template) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyDescription>This server could not be found.</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button variant="outline" onClick={() => setSceneView('marketplace')}>
                        Back to marketplace
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }

    const name = installation?.name ?? template?.name ?? ''
    const description = installation?.description ?? template?.description ?? ''
    const docsUrl = template?.docs_url ?? ''
    const iconDomain = installation?.icon_domain ?? template?.icon_domain ?? null
    const serverUrl = installation?.url ?? template?.url ?? null
    const authType = installation?.auth_type ?? template?.auth_type
    const connected = !!installation && !installation.pending_oauth && !installation.needs_reauth

    return (
        <div className="flex flex-col gap-4">
            <div>
                <Button onClick={onBack}>
                    <IconChevronLeft />
                    Back to marketplace
                </Button>
            </div>

            <div className="flex flex-wrap items-center gap-4">
                <ServerIcon iconDomain={iconDomain} serverUrl={serverUrl} size={56} />
                <div className="flex min-w-48 flex-1 flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            {name}
                        </Heading>
                        {connected && <Badge variant="success">Connected</Badge>}
                        {installation?.needs_reauth && <Badge variant="destructive">Reconnect required</Badge>}
                        {installation?.pending_oauth && <Badge variant="warning">Pending OAuth</Badge>}
                        {authType && <Badge>{authType === 'oauth' ? 'OAuth' : 'API key'}</Badge>}
                    </div>
                    {description && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {description}
                        </Text>
                    )}
                    {docsUrl && (
                        <Text size="xs" render={<p className="m-0" />}>
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={<LinkPrimitive to={docsUrl} target="_blank" />}
                            >
                                View documentation
                            </Button>
                        </Text>
                    )}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    {!installation && template ? (
                        <Button
                            variant="primary"
                            onClick={() => installTemplate({ templateId: template.id })}
                            disabledReason={restrictedReason}
                        >
                            Connect
                        </Button>
                    ) : installation?.needs_reauth ? (
                        <Button
                            variant="primary"
                            onClick={() => onContinueOAuth(installation.id)}
                            disabledReason={restrictedReason}
                        >
                            Reconnect
                        </Button>
                    ) : null}
                    {installation && connected && (
                        <Field orientation="horizontal" className="w-fit">
                            <Switch
                                id={enabledSwitchId}
                                checked={installation.is_enabled !== false}
                                onCheckedChange={(checked: boolean) =>
                                    toggleServerEnabled({ id: installation.id, enabled: checked })
                                }
                                disabledReason={mutationDisabledReason}
                            />
                            <FieldLabel htmlFor={enabledSwitchId} className="flex items-center gap-1">
                                Enabled
                                <Tooltip>
                                    <TooltipTrigger
                                        delay={0}
                                        render={<Button size="icon-xs" aria-label="About enabling this server" />}
                                    >
                                        <IconInfo />
                                    </TooltipTrigger>
                                    <TooltipContent className="max-w-80">{ENABLE_HELP}</TooltipContent>
                                </Tooltip>
                            </FieldLabel>
                        </Field>
                    )}
                    {installation?.scope === 'personal' && isOwner && isAdmin && (
                        <Button variant="outline" loading={installationsLoading} onClick={() => onShare(installation)}>
                            <IconShare />
                            Share with project
                        </Button>
                    )}
                    {installation?.scope === 'shared' && (isOwner || isAdmin) && (
                        <Button
                            variant="outline"
                            loading={installationsLoading}
                            onClick={() => unshareInstallation({ id: installation.id })}
                            tooltip="Convert back to a personal server, visible only to its owner."
                        >
                            Unshare
                        </Button>
                    )}
                    {installation && (
                        <Button
                            variant="destructive-outline"
                            loading={installationsLoading}
                            onClick={() => uninstallServer(installation.id)}
                            disabledReason={removeDisabledReason}
                        >
                            <IconTrash />
                            Remove
                        </Button>
                    )}
                </div>
            </div>

            <Separator />

            {installation ? (
                children
            ) : (
                <Empty className="rounded-md border border-dashed border-border">
                    <EmptyHeader>
                        <EmptyDescription>Connect this server to manage its tools and permissions.</EmptyDescription>
                    </EmptyHeader>
                </Empty>
            )}
        </div>
    )
}
