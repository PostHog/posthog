import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheck, IconEllipsis, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonInput, LemonModal, LemonTag, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { CategoryProgress, customerIOImportLogic } from './customerIOImportLogic'

export function CustomerIOImportModal(): JSX.Element {
    const { isImportModalOpen, isImporting, importProgress, importError, importForm } = useValues(customerIOImportLogic)
    const { closeImportModal, submitImportForm } = useActions(customerIOImportLogic)

    const renderProgressBar = (): JSX.Element | null => {
        if (!importProgress) {
            return null
        }

        const { current_category_index, total_categories } = importProgress

        if (total_categories && total_categories > 0 && current_category_index) {
            // Don't show 100% until actually completed - show max 99% during processing
            const rawProgress = (current_category_index / total_categories) * 100
            const categoryProgress = importProgress.status === 'completed' ? 100 : Math.min(99, rawProgress)

            return (
                <div className="space-y-2">
                    <div className="flex justify-between text-xs text-muted-alt">
                        <span>
                            Category {current_category_index} of {total_categories}
                        </span>
                        <span>{Math.round(categoryProgress)}%</span>
                    </div>
                    <LemonProgress percent={categoryProgress} />
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
                                <LemonBanner type="success" className="mb-4">
                                    <span className="font-semibold">Import Complete!</span>
                                </LemonBanner>
                                <div className="space-y-2 text-sm">
                                    <div className="flex items-center justify-between">
                                        <span>Categories imported:</span>
                                        <LemonTag>{importProgress.topics_found}</LemonTag>
                                    </div>
                                    <LemonDivider className="my-2" />
                                    <div className="flex items-center justify-between">
                                        <span>Unique customers with opt-outs:</span>
                                        <LemonTag>{importProgress.customers_processed.toLocaleString()}</LemonTag>
                                    </div>
                                    <div className="flex items-center justify-between">
                                        <span>Total opt-out preferences imported:</span>
                                        <LemonTag>{importProgress.preferences_updated.toLocaleString()}</LemonTag>
                                    </div>
                                </div>
                                {importProgress.preferences_updated > importProgress.customers_processed && (
                                    <div className="text-xs text-muted-alt mt-2">
                                        Note: Some customers have opted out of multiple categories
                                    </div>
                                )}
                                {importProgress.errors && importProgress.errors.length > 0 && (
                                    <LemonBanner type="warning" className="mt-4">
                                        <div>
                                            <div className="font-semibold mb-2">Some errors occurred:</div>
                                            <div className="text-xs max-h-32 overflow-y-auto">
                                                {importProgress.errors.slice(0, 10).map((error, idx) => (
                                                    <div key={idx}>• {error}</div>
                                                ))}
                                                {importProgress.errors.length > 10 && (
                                                    <div className="mt-1">
                                                        ... and {importProgress.errors.length - 10} more errors
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    </LemonBanner>
                                )}
                            </>
                        ) : importProgress?.status === 'failed' ? (
                            <LemonBanner type="error">
                                <div>
                                    <div className="font-semibold mb-2">Import Failed</div>
                                    <div className="text-sm">
                                        {importProgress.errors?.join(', ') || 'An unknown error occurred'}
                                    </div>
                                </div>
                            </LemonBanner>
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
                                    <div className="mt-4 space-y-2">
                                        {importProgress.topics_found > 0 && (
                                            <div className="flex items-center gap-2 text-xs">
                                                <IconCheck className="text-success" />
                                                <span>Found {importProgress.topics_found} categories</span>
                                            </div>
                                        )}

                                        {/* Show categories list with their status */}
                                        {importProgress.categories_list &&
                                            importProgress.categories_list.length > 0 && (
                                                <>
                                                    <LemonDivider className="my-2" />
                                                    <div className="space-y-1">
                                                        {importProgress.categories_list.map(
                                                            (category: CategoryProgress, idx: number) => (
                                                                <div
                                                                    key={idx}
                                                                    className="flex items-center gap-2 text-xs"
                                                                >
                                                                    {category.status === 'completed' ? (
                                                                        <IconCheck className="text-success" />
                                                                    ) : category.status === 'processing' ? (
                                                                        <Spinner className="text-xs" />
                                                                    ) : (
                                                                        <IconEllipsis className="text-muted-alt" />
                                                                    )}
                                                                    <span
                                                                        className={
                                                                            category.status === 'processing'
                                                                                ? 'font-semibold'
                                                                                : ''
                                                                        }
                                                                    >
                                                                        {category.name}
                                                                    </span>
                                                                </div>
                                                            )
                                                        )}
                                                    </div>
                                                </>
                                            )}

                                        <LemonDivider className="my-2" />
                                        <div className="flex gap-4 text-xs text-muted-alt">
                                            {importProgress.customers_processed > 0 && (
                                                <span>
                                                    Total customers:{' '}
                                                    <strong>
                                                        {importProgress.customers_processed.toLocaleString()}
                                                    </strong>
                                                </span>
                                            )}
                                            {importProgress.preferences_updated > 0 && (
                                                <span>
                                                    Total preferences:{' '}
                                                    <strong>
                                                        {importProgress.preferences_updated.toLocaleString()}
                                                    </strong>
                                                </span>
                                            )}
                                        </div>
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

                    {importError && (
                        <LemonBanner type="error" className="text-sm">
                            {importError}
                        </LemonBanner>
                    )}

                    <div className="text-xs text-muted-alt">
                        <p>This import will:</p>
                        <ul className="list-disc list-inside mt-1 space-y-1">
                            <li>Import all Customer.io subscription topics as message categories</li>
                            <li>Import all customers who have opted out of any topics</li>
                            <li>Preserve their opt-out preferences for each topic</li>
                        </ul>
                        <div className="mt-1 p-2 bg-warning-highlight rounded">
                            <div className="flex items-start gap-2">
                                <IconWarning className="text-warning shrink-0 mt-0.5" />
                                <p className="text-xs">
                                    The import duration depends on your customer base size. Large imports (100k+
                                    customers) may take several minutes to complete.
                                </p>
                            </div>
                        </div>
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
                isImporting ||
                (importProgress &&
                    importProgress.status !== 'completed' &&
                    importProgress.status !== 'failed') ? null : importProgress?.status === 'completed' || // Hide all buttons during import
                  importProgress?.status === 'failed' ? (
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
