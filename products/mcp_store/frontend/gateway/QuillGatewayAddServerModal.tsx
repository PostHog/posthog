import { useActions, useValues } from 'kea'

import {
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldContent,
    FieldDescription,
    FieldError,
    FieldLabel,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Switch,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { InstallCustomAuthTypeEnumApi } from '../generated/api.schemas'
import { OAuthRedirectUri } from '../OAuthRedirectUri'
import { isValidMcpUrl } from './gatewayAddServer'
import { AGENT_GRANT_SCOPE_OPTIONS } from './gatewayUtils'
import { mcpGatewayLogic } from './mcpGatewayLogic'

const AUTH_TYPE_OPTIONS = [
    { value: 'oauth' as const, label: 'OAuth' },
    { value: 'api_key' as const, label: 'API key' },
]

export function QuillGatewayAddServerModal(): JSX.Element | null {
    const {
        addServerForm,
        addServerModalOpen,
        addServerSubmitDisabledReason,
        addingServer,
        canManageAgentAccess,
        isAdmin,
    } = useValues(mcpGatewayLogic)
    const { closeAddServerModal, setAddServerFormValue, submitAddServer } = useActions(mcpGatewayLogic)

    if (!addServerModalOpen) {
        return null
    }

    const closeModal = (): void => {
        if (!addingServer) {
            closeAddServerModal()
        }
    }

    const urlError =
        addServerForm.url.trim() && !isValidMcpUrl(addServerForm.url)
            ? 'Enter a full URL, like https://mcp.example.com/mcp.'
            : undefined

    return (
        <Dialog
            open
            onOpenChange={(open: boolean) => {
                if (!open) {
                    closeModal()
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Add MCP server</DialogTitle>
                    <DialogDescription>Connect a remote MCP server and choose how far to share it.</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <form
                        id="mcp-gateway-add-server-form"
                        className="flex flex-col gap-4"
                        onSubmit={(event) => {
                            event.preventDefault()

                            if (!addServerSubmitDisabledReason) {
                                submitAddServer()
                            }
                        }}
                    >
                        <Field>
                            <FieldLabel htmlFor="mcp-gateway-server-name">Name</FieldLabel>
                            <Input
                                id="mcp-gateway-server-name"
                                value={addServerForm.name}
                                onChange={(event) => setAddServerFormValue('name', event.target.value)}
                                placeholder="Linear"
                                maxLength={200}
                                autoFocus
                            />
                        </Field>

                        <Field data-invalid={urlError ? true : undefined}>
                            <FieldLabel htmlFor="mcp-gateway-server-url">Server URL</FieldLabel>
                            <Input
                                id="mcp-gateway-server-url"
                                type="url"
                                value={addServerForm.url}
                                onChange={(event) => setAddServerFormValue('url', event.target.value)}
                                placeholder="https://mcp.example.com/mcp"
                                maxLength={2048}
                                aria-invalid={Boolean(urlError)}
                            />
                            <FieldDescription>Use the full HTTP or HTTPS URL exposed by the server.</FieldDescription>
                            {urlError && <FieldError>{urlError}</FieldError>}
                        </Field>

                        <Field>
                            <FieldLabel htmlFor="mcp-gateway-server-description">Description (optional)</FieldLabel>
                            <Input
                                id="mcp-gateway-server-description"
                                value={addServerForm.description}
                                onChange={(event) => setAddServerFormValue('description', event.target.value)}
                                placeholder="What this server helps with"
                            />
                        </Field>

                        <Field>
                            <FieldLabel htmlFor="mcp-gateway-server-authentication">Authentication</FieldLabel>
                            <Select
                                value={addServerForm.authType}
                                onValueChange={(next) =>
                                    setAddServerFormValue('authType', next as InstallCustomAuthTypeEnumApi)
                                }
                            >
                                <SelectTrigger id="mcp-gateway-server-authentication" className="w-full">
                                    <SelectValue>
                                        {(selected: string) =>
                                            AUTH_TYPE_OPTIONS.find((option) => option.value === selected)?.label
                                        }
                                    </SelectValue>
                                </SelectTrigger>
                                <SelectContent>
                                    {AUTH_TYPE_OPTIONS.map((option) => (
                                        <SelectItem key={option.value} value={option.value}>
                                            {option.label}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </Field>

                        {addServerForm.authType === 'api_key' ? (
                            <Field>
                                <FieldLabel htmlFor="mcp-gateway-server-api-key">API key (optional)</FieldLabel>
                                <Input
                                    id="mcp-gateway-server-api-key"
                                    type="password"
                                    value={addServerForm.apiKey}
                                    onChange={(event) => setAddServerFormValue('apiKey', event.target.value)}
                                    placeholder="Enter API key"
                                />
                                <FieldDescription>
                                    Leave this blank if the server does not require authentication.
                                </FieldDescription>
                            </Field>
                        ) : (
                            <Collapsible>
                                <CollapsibleTrigger className="w-full">Advanced OAuth settings</CollapsibleTrigger>
                                <CollapsibleContent>
                                    <div className="flex flex-col gap-4 pt-2">
                                        <OAuthRedirectUri />
                                        <Field>
                                            <FieldLabel htmlFor="mcp-gateway-server-client-id">
                                                OAuth client ID (optional)
                                            </FieldLabel>
                                            <Input
                                                id="mcp-gateway-server-client-id"
                                                value={addServerForm.clientId}
                                                onChange={(event) =>
                                                    setAddServerFormValue('clientId', event.target.value)
                                                }
                                            />
                                            <FieldDescription>
                                                Leave blank to let PostHog register a client.
                                            </FieldDescription>
                                        </Field>
                                        <Field>
                                            <FieldLabel htmlFor="mcp-gateway-server-client-secret">
                                                OAuth client secret (optional)
                                            </FieldLabel>
                                            <Input
                                                id="mcp-gateway-server-client-secret"
                                                type="password"
                                                value={addServerForm.clientSecret}
                                                onChange={(event) =>
                                                    setAddServerFormValue('clientSecret', event.target.value)
                                                }
                                            />
                                        </Field>
                                    </div>
                                </CollapsibleContent>
                            </Collapsible>
                        )}

                        {isAdmin && (
                            <Field orientation="horizontal" className="rounded-md border border-border p-3">
                                <FieldContent>
                                    <FieldLabel htmlFor="mcp-gateway-server-team-enabled">
                                        Enabled for your organization
                                    </FieldLabel>
                                    <FieldDescription>
                                        Anyone in your organization can find and use this server. Each person connects
                                        with their own account.
                                    </FieldDescription>
                                </FieldContent>
                                <Switch
                                    id="mcp-gateway-server-team-enabled"
                                    checked={addServerForm.teamEnabled}
                                    onCheckedChange={(teamEnabled: boolean) =>
                                        setAddServerFormValue('teamEnabled', teamEnabled)
                                    }
                                    aria-label="Make server available to team members"
                                />
                            </Field>
                        )}

                        {canManageAgentAccess && (
                            <Field orientation="horizontal" className="flex-wrap rounded-md border border-border p-3">
                                <FieldContent>
                                    <FieldLabel>Who can use this connection?</FieldLabel>
                                    <FieldDescription>
                                        {addServerForm.agentScope === 'team'
                                            ? 'Anyone in this project can use this connection'
                                            : 'Only you can use this connection'}
                                    </FieldDescription>
                                </FieldContent>
                                <ToggleGroup
                                    size="sm"
                                    value={[addServerForm.agentScope]}
                                    onValueChange={(next: string[]) => {
                                        const picked = AGENT_GRANT_SCOPE_OPTIONS.find(
                                            (option) => option.value === next[0]
                                        )

                                        if (picked) {
                                            setAddServerFormValue('agentScope', picked.value)
                                        }
                                    }}
                                    className="flex-wrap"
                                >
                                    {AGENT_GRANT_SCOPE_OPTIONS.map((option) => (
                                        <Tooltip key={option.value}>
                                            <TooltipTrigger render={<ToggleGroupItem value={option.value} />}>
                                                {option.label}
                                            </TooltipTrigger>
                                            <TooltipContent>{option.tooltip}</TooltipContent>
                                        </Tooltip>
                                    ))}
                                </ToggleGroup>
                            </Field>
                        )}
                    </form>
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeModal}
                        disabledReason={addingServer ? 'Adding server' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        type="submit"
                        form="mcp-gateway-add-server-form"
                        loading={addingServer}
                        disabledReason={addServerSubmitDisabledReason ?? undefined}
                    >
                        Add server
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
