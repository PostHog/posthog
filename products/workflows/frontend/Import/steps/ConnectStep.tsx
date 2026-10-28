import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { ImportStepFooter } from '../components/ImportStepFooter'
import { customerIOImportLogic } from '../customerIOImportLogic'

export function ConnectStep(): JSX.Element {
    const { importForm, hasStoredKey, isRemovingAppConfig } = useValues(customerIOImportLogic)
    const { setStep, removeAppConfig } = useActions(customerIOImportLogic)

    return (
        <div className="space-y-4">
            {hasStoredKey ? (
                <div className="space-y-2">
                    <label className="LemonLabel">Customer.io App API key</label>
                    <LemonInput
                        value="••••••••••••••••"
                        disabledReason="Remove the saved key to use a different one"
                        suffix={
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                status="danger"
                                tooltip="Remove the saved API key"
                                onClick={removeAppConfig}
                                loading={isRemovingAppConfig}
                                icon={<IconTrash className="text-danger" />}
                                data-attr="customerio-import-remove-key"
                            />
                        }
                    />
                    <p className="text-xs text-secondary m-0">Your App API key is saved for this project.</p>
                </div>
            ) : (
                <Form logic={customerIOImportLogic} formKey="importForm">
                    <LemonField
                        name="app_api_key"
                        label="Customer.io App API key"
                        help="Create one in Customer.io under Settings → Account settings → API credentials. We check it when the import starts."
                    >
                        <LemonInput
                            placeholder="Enter your App API key"
                            type="password"
                            data-attr="customerio-api-key"
                            autoComplete="off"
                        />
                    </LemonField>
                </Form>
            )}
            <ImportStepFooter>
                <LemonButton
                    type="primary"
                    onClick={() => setStep('choose')}
                    disabledReason={!hasStoredKey && !importForm.app_api_key ? 'Enter your API key' : undefined}
                    data-attr="messaging-import-connect-next"
                >
                    Next
                </LemonButton>
            </ImportStepFooter>
        </div>
    )
}
