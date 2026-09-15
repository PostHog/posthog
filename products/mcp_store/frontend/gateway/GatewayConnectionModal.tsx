import { useActions, useValues } from 'kea'

import { LemonButton, LemonCollapse, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { InstallCustomAuthTypeEnumApi } from '../generated/api.schemas'
import { mcpGatewayLogic } from './mcpGatewayLogic'

const AUTH_TYPE_OPTIONS = [
    { value: 'oauth' as const, label: 'OAuth' },
    { value: 'api_key' as const, label: 'API key' },
]

export function GatewayConnectionModal(): JSX.Element | null {
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
        <LemonModal
            isOpen
            onClose={closeModal}
            title={`Connect ${connectionModalServer.name}`}
            description={
                memberChooses
                    ? 'Choose how this server authenticates, then enter your personal credentials.'
                    : connectionAuthType === 'api_key'
                      ? 'This server uses an API key. Enter your own key to connect.'
                      : 'Enter the credentials for your personal connection.'
            }
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={connecting ? 'Connection in progress' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        form="mcp-gateway-connect-server-form"
                        loading={connecting}
                        disabledReason={connectionSubmitDisabledReason ?? undefined}
                    >
                        Connect
                    </LemonButton>
                </div>
            }
            width={560}
        >
            <form
                id="mcp-gateway-connect-server-form"
                className="flex flex-col gap-3"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (!connecting && !connectionSubmitDisabledReason) {
                        submitConnection()
                    }
                }}
            >
                {memberChooses && (
                    <LemonField.Pure label="Authentication" htmlFor="mcp-gateway-connection-authentication">
                        <LemonSelect<InstallCustomAuthTypeEnumApi>
                            id="mcp-gateway-connection-authentication"
                            value={connectionAuthType}
                            onChange={setConnectionAuthType}
                            options={AUTH_TYPE_OPTIONS}
                            fullWidth
                        />
                    </LemonField.Pure>
                )}

                {connectionAuthType === 'api_key' ? (
                    <LemonField.Pure
                        label={isCustomServer ? 'API key (optional)' : 'API key'}
                        help={
                            isCustomServer
                                ? 'Leave this blank if the server does not require authentication.'
                                : undefined
                        }
                        htmlFor="mcp-gateway-connection-api-key"
                    >
                        <LemonInput
                            id="mcp-gateway-connection-api-key"
                            type="password"
                            value={connectionApiKey}
                            onChange={setConnectionApiKey}
                            placeholder="Enter API key"
                            autoFocus
                            fullWidth
                        />
                    </LemonField.Pure>
                ) : (
                    isCustomServer && (
                        <LemonCollapse
                            panels={[
                                {
                                    key: 'oauth-settings',
                                    header: 'Advanced OAuth settings',
                                    content: (
                                        <div className="flex flex-col gap-3">
                                            <LemonField.Pure
                                                label="OAuth client ID"
                                                help="Leave blank to let PostHog register a client for you."
                                                htmlFor="mcp-gateway-connection-client-id"
                                            >
                                                <LemonInput
                                                    id="mcp-gateway-connection-client-id"
                                                    value={connectionClientId}
                                                    onChange={setConnectionClientId}
                                                    placeholder="Optional"
                                                    fullWidth
                                                />
                                            </LemonField.Pure>
                                            <LemonField.Pure
                                                label="OAuth client secret"
                                                help="Only needed for confidential clients."
                                                htmlFor="mcp-gateway-connection-client-secret"
                                            >
                                                <LemonInput
                                                    id="mcp-gateway-connection-client-secret"
                                                    type="password"
                                                    value={connectionClientSecret}
                                                    onChange={setConnectionClientSecret}
                                                    placeholder="Optional"
                                                    fullWidth
                                                />
                                            </LemonField.Pure>
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    )
                )}
            </form>
        </LemonModal>
    )
}
