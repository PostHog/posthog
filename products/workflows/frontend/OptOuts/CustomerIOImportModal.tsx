import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheck, IconUpload, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonInput, LemonModal, LemonTag, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'

import { CSVImportProgress, customerIOImportLogic } from './customerIOImportLogic'

export function CustomerIOImportModal(): JSX.Element {
    const { 
        isImportModalOpen, 
        isImporting, 
        importProgress, 
        importError, 
        importForm,
        csvFile,
        csvProgress,
        showCSVPhase,
        isUploadingCSV
    } = useValues(customerIOImportLogic)
    const { 
        closeImportModal, 
        submitImportForm,
        setCSVFile,
        uploadCSV
    } = useActions(customerIOImportLogic)

    const renderAPIImportPhase = (): JSX.Element => {
        if (isImporting || (importProgress && importProgress.status !== 'completed' && importProgress.status !== 'failed')) {
            // Show progress
            return (
                <div className="space-y-4">
                    <div className="text-center">
                        <Spinner className="text-3xl mb-4" />
                        <div className="text-lg font-semibold mb-2">Importing from Customer.io API...</div>
                        <div className="text-sm text-muted-alt">
                            {importProgress?.details || 'Starting import...'}
                        </div>
                    </div>
                    
                    {importProgress && (
                        <div className="space-y-2 text-sm">
                            {importProgress.topics_found > 0 && (
                                <div className="flex items-center gap-2">
                                    <IconCheck className="text-success" />
                                    <span>Found {importProgress.topics_found} subscription topics</span>
                                </div>
                            )}
                            {(importProgress.categories_created ?? 0) > 0 && (
                                <div className="flex items-center gap-2">
                                    <IconCheck className="text-success" />
                                    <span>Created {importProgress.categories_created} categories</span>
                                </div>
                            )}
                            {(importProgress.globally_unsubscribed_count ?? 0) > 0 && (
                                <div className="flex items-center gap-2">
                                    <Spinner className="text-xs" />
                                    <span>Processing {(importProgress.globally_unsubscribed_count ?? 0).toLocaleString()} globally unsubscribed users...</span>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )
        }

        if (importProgress?.status === 'failed') {
            return (
                <LemonBanner type="error">
                    <div>
                        <div className="font-semibold mb-2">Import Failed</div>
                        <div className="text-sm">
                            {importProgress.errors?.join(', ') || 'An unknown error occurred'}
                        </div>
                    </div>
                </LemonBanner>
            )
        }

        if (importProgress?.status === 'completed') {
            return (
                <div className="space-y-4">
                    <LemonBanner type="success">
                        <span className="font-semibold">API Import Complete!</span>
                    </LemonBanner>
                    <div className="space-y-2 text-sm">
                        <div className="flex items-center justify-between">
                            <span>Categories imported:</span>
                            <LemonTag>{importProgress.categories_created || 0}</LemonTag>
                        </div>
                        <div className="flex items-center justify-between">
                            <span>Globally unsubscribed users:</span>
                            <LemonTag>{(importProgress.globally_unsubscribed_count || 0).toLocaleString()}</LemonTag>
                        </div>
                    </div>
                </div>
            )
        }

        // Initial form
        return (
            <Form logic={customerIOImportLogic} formKey="importForm" enableFormOnSubmit>
                <div className="space-y-4">
                    <div>
                        <p className="text-sm text-muted mb-4">
                            Step 1: Import categories and globally unsubscribed users from Customer.io API.
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

                    {importError && (
                        <LemonBanner type="error" className="text-sm">
                            {importError}
                        </LemonBanner>
                    )}

                    <div className="text-xs text-muted-alt">
                        You can generate an App API key in Customer.io under Settings → Account Settings → API Credentials.
                    </div>
                </div>
            </Form>
        )
    }

    const renderCSVImportPhase = (): JSX.Element => {
        const renderFailedImports = (failed: CSVImportProgress['failed_imports']): JSX.Element | null => {
            if (!failed || failed.length === 0) return null
            
            return (
                <div className="mt-4">
                    <div className="font-semibold mb-2">Failed imports ({failed.length}):</div>
                    <div className="max-h-32 overflow-y-auto bg-bg-light rounded p-2 text-xs font-mono">
                        {failed.slice(0, 100).map((item, idx) => (
                            <div key={idx} className="py-0.5">
                                {item.email}: {item.error}
                            </div>
                        ))}
                        {failed.length > 100 && (
                            <div className="text-muted-alt mt-2">
                                ... and {failed.length - 100} more
                            </div>
                        )}
                    </div>
                </div>
            )
        }

        // Show loading state while processing
        if (isUploadingCSV && !csvProgress) {
            return (
                <div className="space-y-4">
                    <LemonDivider />
                    <div className="text-center py-8">
                        <Spinner className="text-3xl mb-4" />
                        <div className="text-lg font-semibold mb-2">Processing CSV...</div>
                        <div className="text-sm text-muted-alt">
                            This may take a moment for large files. Please don't close this window.
                        </div>
                        <div className="text-xs text-muted-alt mt-2">
                            Processing thousands of rows and updating the database...
                        </div>
                    </div>
                </div>
            )
        }

        if (csvProgress) {
            if (csvProgress.status === 'completed') {
                return (
                    <div className="space-y-4">
                        <LemonDivider />
                        <LemonBanner type="success">
                            <span className="font-semibold">CSV Import Complete!</span>
                        </LemonBanner>
                        <div className="space-y-2 text-sm">
                            <div className="flex items-center justify-between">
                                <span>Total rows processed:</span>
                                <LemonTag>{csvProgress.total_rows.toLocaleString()}</LemonTag>
                            </div>
                            <div className="flex items-center justify-between">
                                <span>Users with opt-outs:</span>
                                <LemonTag>{csvProgress.users_with_optouts.toLocaleString()}</LemonTag>
                            </div>
                            <div className="flex items-center justify-between">
                                <span>Users skipped (no opt-outs):</span>
                                <LemonTag>{csvProgress.users_skipped.toLocaleString()}</LemonTag>
                            </div>
                            {csvProgress.parse_errors > 0 && (
                                <div className="flex items-center justify-between text-warning">
                                    <span>Parse errors:</span>
                                    <LemonTag type="warning">{csvProgress.parse_errors}</LemonTag>
                                </div>
                            )}
                            <LemonDivider />
                            <div className="flex items-center justify-between font-semibold">
                                <span>Total preferences imported:</span>
                                <LemonTag type="success">{csvProgress.preferences_updated.toLocaleString()}</LemonTag>
                            </div>
                        </div>
                        {renderFailedImports(csvProgress.failed_imports)}
                    </div>
                )
            } else if (csvProgress.status === 'failed') {
                return (
                    <div className="space-y-4">
                        <LemonDivider />
                        <LemonBanner type="error">
                            <div>
                                <div className="font-semibold mb-2">CSV Import Failed</div>
                                <div className="text-sm">{csvProgress.details}</div>
                            </div>
                        </LemonBanner>
                    </div>
                )
            }
        }

        return (
            <div className="space-y-4">
                <LemonDivider />
                <div>
                    <h3 className="font-semibold mb-2">Step 2: Import User Preferences (Optional)</h3>
                    <p className="text-sm text-muted mb-4">
                        Export a CSV from Customer.io with users who have subscription preferences set.
                    </p>
                    
                    <div className="bg-bg-light rounded p-3 mb-4">
                        <div className="text-sm font-semibold mb-2">Required CSV columns:</div>
                        <ul className="text-xs space-y-1">
                            <li>• <code>id</code> - Customer.io ID</li>
                            <li>• <code>email</code> - Customer email address</li>
                            <li>• <code>cio_subscription_preferences</code> - JSON preferences data</li>
                        </ul>
                        <div className="mt-3">
                            <a 
                                href="https://posthog.com/docs/workflows/customerio-import" 
                                target="_blank" 
                                rel="noopener noreferrer"
                                className="text-xs text-primary hover:underline"
                            >
                                View detailed export instructions →
                            </a>
                        </div>
                    </div>

                    <LemonFileInput
                        accept=".csv"
                        multiple={false}
                        value={csvFile ? [csvFile] : []}
                        onChange={(files) => setCSVFile(files[0] || null)}
                        showUploadedFiles={true}
                        callToAction={
                            <div className="flex items-center gap-2">
                                <IconUpload />
                                <span>Choose CSV file</span>
                            </div>
                        }
                    />
                    
                    {csvFile && (
                        <div className="mt-2 text-xs text-muted">
                            File size: {(csvFile.size / (1024 * 1024)).toFixed(2)}MB
                        </div>
                    )}
                </div>
            </div>
        )
    }

    const renderContent = (): JSX.Element => {
        if (!showCSVPhase) {
            return renderAPIImportPhase()
        }
        
        return (
            <div className="space-y-4">
                {renderAPIImportPhase()}
                {renderCSVImportPhase()}
            </div>
        )
    }

    const getModalFooter = (): JSX.Element | null => {
        // During API import
        if (isImporting || (importProgress && importProgress.status !== 'completed' && importProgress.status !== 'failed')) {
            return null // No buttons during import
        }

        // During CSV upload/processing
        if (isUploadingCSV && !csvProgress) {
            return null // No buttons while processing
        }

        // API import failed
        if (importProgress?.status === 'failed') {
            return (
                <LemonButton type="primary" onClick={closeImportModal}>
                    Close
                </LemonButton>
            )
        }

        // CSV phase
        if (showCSVPhase) {
            if (csvProgress?.status === 'completed' || csvProgress?.status === 'failed') {
                return (
                    <LemonButton type="primary" onClick={closeImportModal}>
                        Close
                    </LemonButton>
                )
            }
            
            return (
                <>
                    <LemonButton 
                        type="secondary" 
                        onClick={closeImportModal}
                    >
                        Skip CSV Import
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={uploadCSV}
                        loading={isUploadingCSV}
                        disabledReason={!csvFile ? 'Please select a CSV file' : undefined}
                    >
                        Upload & Process CSV
                    </LemonButton>
                </>
            )
        }

        // Initial API import form
        return (
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

    return (
        <LemonModal
            title="Import from Customer.io"
            isOpen={isImportModalOpen}
            onClose={closeImportModal}
            footer={getModalFooter()}
            width="medium"
        >
            {renderContent()}
        </LemonModal>
    )
}