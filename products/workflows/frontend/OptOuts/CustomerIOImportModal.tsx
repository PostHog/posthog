import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { customerIOImportLogic } from './customerIOImportLogic'

export function CustomerIOImportModal(): JSX.Element {
    const { isImportModalOpen, isImporting, importProgress, importError, importForm } = useValues(customerIOImportLogic)
    const { closeImportModal, submitImportForm } = useActions(customerIOImportLogic)

    const renderProgressBar = (): JSX.Element | null => {
        if (!importProgress) return null
        
        const { 
            current_category_index, 
            total_categories,
            customers_in_current_batch
        } = importProgress
        
        if (total_categories && total_categories > 0 && current_category_index) {
            const categoryProgress = (current_category_index / total_categories) * 100
            
            return (
                <div className="space-y-2">
                    <div className="flex justify-between text-xs text-muted-alt">
                        <span>Topic {current_category_index} of {total_categories}</span>
                        <span>{Math.round(categoryProgress)}%</span>
                    </div>
                    <LemonProgress percent={categoryProgress} />
                    {customers_in_current_batch && customers_in_current_batch > 0 && (
                        <div className="text-xs text-muted-alt">
                            Processing {customers_in_current_batch} customers with opt-outs
                        </div>
                    )}
                </div>
            )
        }
        
        return null
    }

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
                                    <p>Categories created: {importProgress.categories_created || importProgress.workflows_created}</p>
                                    <p>Unique customers processed: {importProgress.customers_processed}</p>
                                    <p>Total opt-outs imported: {importProgress.preferences_updated}</p>
                                </div>
                                {importProgress.errors && importProgress.errors.length > 0 && (
                                    <div className="mt-4">
                                        <div className="text-warning font-semibold">Some errors occurred:</div>
                                        <div className="text-xs text-muted-alt mt-2 max-h-32 overflow-y-auto">
                                            {importProgress.errors.slice(0, 10).map((error, idx) => (
                                                <div key={idx}>{error}</div>
                                            ))}
                                            {importProgress.errors.length > 10 && (
                                                <div>... and {importProgress.errors.length - 10} more errors</div>
                                            )}
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
                                
                                {importProgress?.status === 'creating_categories' && (
                                    <div className="text-sm text-muted-alt mb-4">
                                        Creating message categories from Customer.io topics...
                                    </div>
                                )}
                                
                                {importProgress?.status?.startsWith('processing_category') && (
                                    <>
                                        <div className="text-sm text-muted-alt mb-4">
                                            {importProgress.details || 'Processing customer opt-outs...'}
                                        </div>
                                        {renderProgressBar()}
                                    </>
                                )}
                                
                                {importProgress && (
                                    <div className="mt-4 space-y-1 text-xs">
                                        {importProgress.topics_found > 0 && (
                                            <p>✓ Found {importProgress.topics_found} topics</p>
                                        )}
                                        {((importProgress.categories_created || importProgress.workflows_created || 0) > 0) && (
                                            <p>✓ Created {importProgress.categories_created || importProgress.workflows_created} categories</p>
                                        )}
                                        {importProgress.current_category && (
                                            <p>Currently importing opt-outs for: {importProgress.current_category}</p>
                                        )}
                                        {importProgress.customers_processed > 0 && (
                                            <p>Customers found with opt-outs: {importProgress.customers_processed}</p>
                                        )}
                                        {importProgress.preferences_updated > 0 && (
                                            <p>Opt-outs imported: {importProgress.preferences_updated}</p>
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
                        <p className="mt-2 text-warning">
                            Note: The import duration depends on your customer base size. Large imports (100k+ customers) may take several minutes to complete.
                        </p>
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
                isImporting || (importProgress && importProgress.status !== 'completed' && importProgress.status !== 'failed') ? (
                    // Hide all buttons during import
                    null
                ) : importProgress?.status === 'completed' || importProgress?.status === 'failed' ? (
                    <LemonButton type="primary" onClick={closeImportModal}>
                        Close
                    </LemonButton>
                ) : (
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
                )
            }
            width="medium"
        >
            {renderContent()}
        </LemonModal>
    )
}