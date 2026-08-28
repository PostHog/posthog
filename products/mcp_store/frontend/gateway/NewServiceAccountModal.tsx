import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { mcpGatewayLogic } from './mcpGatewayLogic'

export function NewServiceAccountModal(): JSX.Element | null {
    const {
        newServiceAccountModalOpen,
        newServiceAccountForm,
        newServiceAccountSubmitDisabledReason,
        creatingServiceAccount,
    } = useValues(mcpGatewayLogic)
    const { closeNewServiceAccountModal, setNewServiceAccountFormValue, createServiceAccount } =
        useActions(mcpGatewayLogic)

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
            </form>
        </LemonModal>
    )
}
