import { useActions, useValues } from 'kea'

import {
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSwitch,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { InstallCustomAuthTypeEnumApi } from '../generated/api.schemas'
import { isValidMcpUrl } from './gatewayAddServer'
import { mcpGatewayLogic } from './mcpGatewayLogic'

const AUTH_TYPE_OPTIONS = [
    { value: 'oauth' as const, label: 'OAuth' },
    { value: 'api_key' as const, label: 'API key' },
]

export function GatewayAddServerModal(): JSX.Element | null {
    const {
        addServerForm,
        addServerModalOpen,
        addServerSubmitDisabledReason,
        addingServer,
        canManageAgentAccess,
        isAdmin,
        serviceAccounts,
        serviceAccountsLoading,
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
    const setAgentSelected = (accountId: string, selected: boolean): void => {
        setAddServerFormValue(
            'agentIds',
            selected
                ? [...addServerForm.agentIds, accountId]
                : addServerForm.agentIds.filter((candidate) => candidate !== accountId)
        )
    }
    const urlError =
        addServerForm.url.trim() && !isValidMcpUrl(addServerForm.url)
            ? 'Enter a full URL, like https://mcp.example.com/mcp.'
            : undefined

    return (
        <LemonModal
            isOpen
            onClose={closeModal}
            title="Add MCP server"
            description="Connect a remote MCP server, then choose who and which agents can use it."
            width={640}
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={addingServer ? 'Adding server' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        form="mcp-gateway-add-server-form"
                        loading={addingServer}
                        disabledReason={addServerSubmitDisabledReason ?? undefined}
                    >
                        Add server
                    </LemonButton>
                </div>
            }
        >
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
                <LemonField.Pure label="Name" htmlFor="mcp-gateway-server-name">
                    <LemonInput
                        id="mcp-gateway-server-name"
                        value={addServerForm.name}
                        onChange={(name) => setAddServerFormValue('name', name)}
                        placeholder="Linear"
                        maxLength={200}
                        autoFocus
                        fullWidth
                    />
                </LemonField.Pure>

                <LemonField.Pure
                    label="Server URL"
                    help="Use the full HTTP or HTTPS URL exposed by the server."
                    htmlFor="mcp-gateway-server-url"
                    error={urlError}
                >
                    <LemonInput
                        id="mcp-gateway-server-url"
                        type="url"
                        value={addServerForm.url}
                        onChange={(url) => setAddServerFormValue('url', url)}
                        placeholder="https://mcp.example.com/mcp"
                        maxLength={2048}
                        aria-invalid={Boolean(urlError)}
                        fullWidth
                    />
                </LemonField.Pure>

                <LemonField.Pure label="Description (optional)" htmlFor="mcp-gateway-server-description">
                    <LemonInput
                        id="mcp-gateway-server-description"
                        value={addServerForm.description}
                        onChange={(description) => setAddServerFormValue('description', description)}
                        placeholder="What this server helps with"
                        fullWidth
                    />
                </LemonField.Pure>

                <LemonField.Pure label="Authentication" htmlFor="mcp-gateway-server-authentication">
                    <LemonSelect<InstallCustomAuthTypeEnumApi>
                        id="mcp-gateway-server-authentication"
                        value={addServerForm.authType}
                        onChange={(authType) => setAddServerFormValue('authType', authType)}
                        options={AUTH_TYPE_OPTIONS}
                        fullWidth
                    />
                </LemonField.Pure>

                {addServerForm.authType === 'api_key' ? (
                    <LemonField.Pure
                        label="API key (optional)"
                        help="Leave this blank if the server does not require authentication."
                        htmlFor="mcp-gateway-server-api-key"
                    >
                        <LemonInput
                            id="mcp-gateway-server-api-key"
                            type="password"
                            value={addServerForm.apiKey}
                            onChange={(apiKey) => setAddServerFormValue('apiKey', apiKey)}
                            placeholder="Enter API key"
                            fullWidth
                        />
                    </LemonField.Pure>
                ) : (
                    <LemonCollapse
                        panels={[
                            {
                                key: 'oauth-settings',
                                header: 'Advanced OAuth settings',
                                content: (
                                    <div className="flex flex-col gap-3">
                                        <LemonField.Pure
                                            label="OAuth client ID (optional)"
                                            help="Leave blank to let PostHog register a client."
                                            htmlFor="mcp-gateway-server-client-id"
                                        >
                                            <LemonInput
                                                id="mcp-gateway-server-client-id"
                                                value={addServerForm.clientId}
                                                onChange={(clientId) => setAddServerFormValue('clientId', clientId)}
                                                fullWidth
                                            />
                                        </LemonField.Pure>
                                        <LemonField.Pure
                                            label="OAuth client secret (optional)"
                                            htmlFor="mcp-gateway-server-client-secret"
                                        >
                                            <LemonInput
                                                id="mcp-gateway-server-client-secret"
                                                type="password"
                                                value={addServerForm.clientSecret}
                                                onChange={(clientSecret) =>
                                                    setAddServerFormValue('clientSecret', clientSecret)
                                                }
                                                fullWidth
                                            />
                                        </LemonField.Pure>
                                    </div>
                                ),
                            },
                        ]}
                    />
                )}

                {isAdmin && (
                    <div className="flex items-center justify-between gap-4 rounded border p-3">
                        <div>
                            <div className="font-semibold">Enabled for your organization</div>
                            <div className="text-sm text-secondary">
                                Anyone in your organization can find and use this server. Each person connects with
                                their own account.
                            </div>
                        </div>
                        <LemonSwitch
                            checked={addServerForm.teamEnabled}
                            onChange={(teamEnabled) => setAddServerFormValue('teamEnabled', teamEnabled)}
                            aria-label="Make server available to team members"
                        />
                    </div>
                )}

                {canManageAgentAccess && (
                    <LemonField.Pure label="Share with agents (optional)">
                        <div className="flex flex-col gap-2 rounded border p-3">
                            {serviceAccountsLoading ? (
                                <span className="text-sm text-secondary">Loading agents…</span>
                            ) : serviceAccounts.length === 0 ? (
                                <span className="text-sm text-secondary">No PostHog agents are available.</span>
                            ) : (
                                serviceAccounts.map((account) => (
                                    <LemonCheckbox
                                        key={account.id}
                                        checked={addServerForm.agentIds.includes(account.id)}
                                        onChange={(checked) => setAgentSelected(account.id, checked)}
                                        label={
                                            <span>
                                                <span className="font-medium">{account.name}</span>
                                                <span className="ml-2 text-xs text-secondary">{account.handle}</span>
                                            </span>
                                        }
                                    />
                                ))
                            )}
                        </div>
                    </LemonField.Pure>
                )}
            </form>
        </LemonModal>
    )
}
