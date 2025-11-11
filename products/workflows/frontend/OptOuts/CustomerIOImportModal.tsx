import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { customerIOImportLogic } from './customerIOImportLogic'

export function CustomerIOImportModal(): JSX.Element {
    const { isImportModalOpen, isImporting, importProgress, importError, importForm } = useValues(customerIOImportLogic)
    const { closeImportModal, submitImportForm } = useActions(customerIOImportLogic)

    const renderContent = (): JSX.Element => {
        if (isImporting || importProgress) {
            return (
                <div className="space-y-4">
                    <div className="text-center">
                        {importProgress?.status === 'completed' ? (
                            <>
                                <div className="text-success text-lg font-semibold mb-4">Import Complete!</div>
                                <div className="space-y-2 text-sm">
                                    <p>Topics found: {importProgress.topics_found}</p>
                                    <p>Workflows created: {importProgress.workflows_created}</p>
                                    <p>Customers processed: {importProgress.customers_processed}</p>
                                    <p>Preferences updated: {importProgress.preferences_updated}</p>
                                </div>
                                {importProgress.errors?.length > 0 && (
                                    <div className="mt-4">
                                        <div className="text-warning font-semibold">Some errors occurred:</div>
                                        <div className="text-xs text-muted-alt mt-2 max-h-32 overflow-y-auto">
                                            {importProgress.errors.map((error, idx) => (
                                                <div key={idx}>{error}</div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </>
                        ) : importProgress?.status === 'failed' ? (
                            <>
                                <div className="text-danger text-lg font-semibold mb-4">Import Failed</div>
                                <div className="text-sm text-muted-alt">
                                    {importProgress.errors?.join(', ') || 'An unknown error occurred'}
                                </div>
                            </>
                        ) : (
                            <>
                                <div className="text-lg font-semibold mb-4">Importing...</div>
                                <div className="text-sm text-muted-alt">
                                    Status: {importProgress?.status || 'Initializing...'}
                                </div>
                                {importProgress && (
                                    <div className="mt-4 space-y-1 text-xs">
                                        {importProgress.topics_found > 0 && (
                                            <p>Topics found: {importProgress.topics_found}</p>
                                        )}
                                        {importProgress.workflows_created > 0 && (
                                            <p>Workflows created: {importProgress.workflows_created}</p>
                                        )}
                                        {importProgress.customers_processed > 0 && (
                                            <p>Customers processed: {importProgress.customers_processed}</p>
                                        )}
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                </div>
            )
        }

        return (
            <Form logic={customerIOImportLogic} formKey="importForm" enableFormOnSubmit>
                <div className="space-y-4">
                    <div>
                        <p className="text-sm text-muted mb-4">
                            Import your Customer.io subscription topics and customer preferences into PostHog Workflows.
                        </p>
                        <p className="text-sm text-muted mb-4">
                            You'll need your Customer.io App API key. You can generate one in your Customer.io account
                            under Settings → Account Settings → API Credentials.
                        </p>
                    </div>

                    <LemonField name="app_api_key" label="Customer.io App API Key">
                        <LemonInput
                            placeholder="Enter your App API key"
                            type="password"
                            data-attr="customerio-api-key"
                            autoComplete="off"
                        />
                    </LemonField>

                    {importError && <div className="text-danger text-sm">{importError}</div>}

                    <div className="text-xs text-muted-alt">
                        <p>This import will:</p>
                        <ul className="list-disc list-inside mt-1 space-y-1">
                            <li>Import all Customer.io subscription topics as message categories</li>
                            <li>Import all customers who have opted out of any topics</li>
                            <li>Preserve their opt-out preferences for each topic</li>
                        </ul>
                    </div>
                </div>
            </Form>
        )
    }

    return (
        <LemonModal
            title="Import from Customer.io"
            isOpen={isImportModalOpen}
            onClose={closeImportModal}
            footer={
                !isImporting && importProgress?.status !== 'completed' && importProgress?.status !== 'failed' ? (
                    <>
                        <LemonButton type="secondary" onClick={closeImportModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={submitImportForm}
                            loading={isImporting}
                            disabledReason={!importForm.app_api_key ? 'Please enter your API key' : undefined}
                        >
                            Start Import
                        </LemonButton>
                    </>
                ) : (
                    <LemonButton type="primary" onClick={closeImportModal}>
                        Close
                    </LemonButton>
                )
            }
            width="medium"
        >
            {renderContent()}
        </LemonModal>
    )
}
