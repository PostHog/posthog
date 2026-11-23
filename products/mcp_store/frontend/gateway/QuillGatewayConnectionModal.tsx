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
    FieldDescription,
    FieldLabel,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { InstallCustomAuthTypeEnumApi } from '../generated/api.schemas'
import { mcpGatewayLogic } from './mcpGatewayLogic'

const AUTH_TYPE_OPTIONS = [
    { value: 'oauth' as const, label: 'OAuth' },
    { value: 'api_key' as const, label: 'API key' },
]

export function QuillGatewayConnectionModal(): JSX.Element | null {
    const {
        connectionModalServer,
        connectionAuthType,
        connectionApiKey,
        connectionClientId,
        connectionClientSecret,
        connectingServerId,
        connectionSubmitDisabledReason,
    } = useValues(mcpGatewayLogic)
    const {
        closeConnectionModal,
        setConnectionAuthType,
        setConnectionApiKey,
        setConnectionClientId,
        setConnectionClientSecret,
        submitConnection,
    } = useActions(mcpGatewayLogic)

    if (!connectionModalServer) {
        return null
    }

    const isCustomServer = !connectionModalServer.template_id
    // Custom servers registered before their auth type was recorded leave the choice to the member.
    const memberChooses = isCustomServer && !connectionModalServer.auth_type
    const connecting = connectingServerId === connectionModalServer.id

    const closeModal = (): void => {
        if (!connecting) {
            closeConnectionModal()
        }
    }

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
                    <DialogTitle>{`Connect ${connectionModalServer.name}`}</DialogTitle>
                    <DialogDescription>
                        {memberChooses
                            ? 'Choose how this server authenticates, then enter your personal credentials.'
                            : connectionAuthType === 'api_key'
                              ? 'This server uses an API key. Enter your own key to connect.'
                              : 'Enter the credentials for your personal connection.'}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <form
                        id="mcp-gateway-connect-server-form"
                        className="flex flex-col gap-4"
                        onSubmit={(event) => {
                            event.preventDefault()

                            if (!connecting && !connectionSubmitDisabledReason) {
                                submitConnection()
                            }
                        }}
                    >
                        {memberChooses && (
                            <Field>
                                <FieldLabel htmlFor="mcp-gateway-connection-authentication">Authentication</FieldLabel>
                                <Select
                                    value={connectionAuthType}
                                    onValueChange={(next) =>
                                        setConnectionAuthType(next as InstallCustomAuthTypeEnumApi)
                                    }
                                >
                                    <SelectTrigger id="mcp-gateway-connection-authentication" className="w-full">
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
                        )}

                        {connectionAuthType === 'api_key' ? (
                            <Field>
                                <FieldLabel htmlFor="mcp-gateway-connection-api-key">
                                    {isCustomServer ? 'API key (optional)' : 'API key'}
                                </FieldLabel>
                                <Input
                                    id="mcp-gateway-connection-api-key"
                                    type="password"
                                    value={connectionApiKey}
                                    onChange={(event) => setConnectionApiKey(event.target.value)}
                                    placeholder="Enter API key"
                                    autoFocus
                                />
                                {isCustomServer && (
                                    <FieldDescription>
                                        Leave this blank if the server does not require authentication.
                                    </FieldDescription>
                                )}
                            </Field>
                        ) : (
                            isCustomServer && (
                                <Collapsible>
                                    <CollapsibleTrigger className="w-full">Advanced OAuth settings</CollapsibleTrigger>
                                    <CollapsibleContent>
                                        <div className="flex flex-col gap-4 pt-2">
                                            <Field>
                                                <FieldLabel htmlFor="mcp-gateway-connection-client-id">
                                                    OAuth client ID
                                                </FieldLabel>
                                                <Input
                                                    id="mcp-gateway-connection-client-id"
                                                    value={connectionClientId}
                                                    onChange={(event) => setConnectionClientId(event.target.value)}
                                                    placeholder="Optional"
                                                />
                                                <FieldDescription>
                                                    Leave blank to let PostHog register a client for you.
                                                </FieldDescription>
                                            </Field>
                                            <Field>
                                                <FieldLabel htmlFor="mcp-gateway-connection-client-secret">
                                                    OAuth client secret
                                                </FieldLabel>
                                                <Input
                                                    id="mcp-gateway-connection-client-secret"
                                                    type="password"
                                                    value={connectionClientSecret}
                                                    onChange={(event) => setConnectionClientSecret(event.target.value)}
                                                    placeholder="Optional"
                                                />
                                                <FieldDescription>
                                                    Only needed for confidential clients.
                                                </FieldDescription>
                                            </Field>
                                        </div>
                                    </CollapsibleContent>
                                </Collapsible>
                            )
                        )}
                    </form>
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeModal}
                        disabledReason={connecting ? 'Connection in progress' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        type="submit"
                        form="mcp-gateway-connect-server-form"
                        loading={connecting}
                        disabledReason={connectionSubmitDisabledReason ?? undefined}
                    >
                        Connect
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
