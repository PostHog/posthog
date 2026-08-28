import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { agentShareDisabledReason } from './gatewayUtils'
import { mcpGatewayLogic } from './mcpGatewayLogic'

export function NewServiceAccountModal(): JSX.Element | null {
    const {
        newServiceAccountModalOpen,
        newServiceAccountForm,
        newServiceAccountSubmitDisabledReason,
        creatingServiceAccount,
        servers,
        serversLoading,
    } = useValues(mcpGatewayLogic)
    const { closeNewServiceAccountModal, setNewServiceAccountFormValue, createServiceAccount } =
        useActions(mcpGatewayLogic)

    const shareableServers = servers.filter((server) => !agentShareDisabledReason(server))
    const setServerSelected = (serverId: string, selected: boolean): void => {
        setNewServiceAccountFormValue(
            'serverIds',
            selected
                ? [...newServiceAccountForm.serverIds, serverId]
                : newServiceAccountForm.serverIds.filter((candidate) => candidate !== serverId)
        )
    }

    if (!newServiceAccountModalOpen) {
        return null
    }

    const closeModal = (): void => {
        if (!creatingServiceAccount) {
            closeNewServiceAccountModal()
        }
    }

    return (
        <LemonModal
            isOpen
            onClose={closeModal}
            title="New service account"
            description="Give an automation, like a workflow, a fixed set of connectors that is separate from any team member's own access."
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={creatingServiceAccount ? 'Creating service account' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        form="mcp-gateway-new-service-account-form"
                        loading={creatingServiceAccount}
                        disabledReason={newServiceAccountSubmitDisabledReason ?? undefined}
                    >
                        Create
                    </LemonButton>
                </div>
            }
        >
            <form
                id="mcp-gateway-new-service-account-form"
                className="flex flex-col gap-4"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (!newServiceAccountSubmitDisabledReason) {
                        createServiceAccount(
                            newServiceAccountForm.name.trim(),
                            newServiceAccountForm.description.trim()
                        )
                    }
                }}
            >
                <LemonField.Pure label="Name" htmlFor="mcp-gateway-new-service-account-name">
                    <LemonInput
                        id="mcp-gateway-new-service-account-name"
                        value={newServiceAccountForm.name}
                        onChange={(name) => setNewServiceAccountFormValue('name', name)}
                        placeholder="SRE"
                        maxLength={200}
                        autoFocus
                        fullWidth
                    />
                </LemonField.Pure>

                <LemonField.Pure label="Description (optional)" htmlFor="mcp-gateway-new-service-account-description">
                    <LemonTextArea
                        id="mcp-gateway-new-service-account-description"
                        value={newServiceAccountForm.description}
                        onChange={(description) => setNewServiceAccountFormValue('description', description)}
                        placeholder="What this service account is for"
                        minRows={2}
                    />
                </LemonField.Pure>

                <LemonField.Pure
                    label="Connectors (optional)"
                    help="Only servers you're connected to can be shared. Share more from the account's page later."
                >
                    <div className="flex flex-col gap-2 rounded border p-3">
                        {serversLoading ? (
                            <span className="text-sm text-secondary">Loading connectors…</span>
                        ) : shareableServers.length === 0 ? (
                            <span className="text-sm text-secondary">
                                Connect a server first, then come back to share it with this account.
                            </span>
                        ) : (
                            shareableServers.map((server) => (
                                <LemonCheckbox
                                    key={server.id}
                                    checked={newServiceAccountForm.serverIds.includes(server.id)}
                                    onChange={(checked) => setServerSelected(server.id, checked)}
                                    label={server.name}
                                />
                            ))
                        )}
                    </div>
                </LemonField.Pure>
            </form>
        </LemonModal>
    )
}
