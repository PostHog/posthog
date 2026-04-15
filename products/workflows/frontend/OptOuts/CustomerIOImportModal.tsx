import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonInput,
    LemonModal,
    LemonTag,
    Link,
    Spinner,
} from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { organizationLogic } from 'scenes/organizationLogic'

import { CSVImportProgress, customerIOImportLogic } from './customerIOImportLogic'

function StepBadge({ status }: { status: 'completed' | 'failed' | false }): JSX.Element | null {
    if (status === 'completed') {
        return <LemonTag type="success">Completed</LemonTag>
    }
    if (status === 'failed') {
        return <LemonTag type="warning">Failed</LemonTag>
    }
    return null
}

function Step1Content(): JSX.Element {
    const { isImporting, importProgress, importError, importForm, syncConfig, isRemovingAppConfig } =
        useValues(customerIOImportLogic)
    const { submitImportForm, rerunImport, removeAppConfig } = useActions(customerIOImportLogic)

    const hasStoredKey = syncConfig?.app_integration_id != null || importProgress?.status === 'completed'
    const result = syncConfig?.app_import_result
    // Prefer local reducer state, fall back to DB-persisted result
    const displayResult = importProgress?.status === 'completed' ? importProgress : null
    const persistedResult = !displayResult && result?.status === 'completed' ? result : null

    if (isImporting) {
        return (
            <div className="text-center py-8">
                <Spinner className="text-3xl mb-4" />
                <div className="text-lg font-semibold mb-2">Importing from Customer.io...</div>
                <div className="text-sm text-muted-alt">
                    This may take a moment. Please don't navigate away from this page.
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            {/* Error banner */}
            {importProgress?.status === 'failed' && (
                <LemonBanner type="error">
                    Import failed: {importProgress.errors?.join(', ') || 'An unknown error occurred'}
                </LemonBanner>
            )}
            {!importProgress && result?.status === 'failed' && (
                <LemonBanner type="error">Last import failed: {result.error || 'Unknown error'}</LemonBanner>
            )}

            {/* Success banner */}
            {(displayResult || persistedResult) && (
                <>
                    <LemonBanner type="success">
                        <span className="font-semibold">API import complete</span>
                    </LemonBanner>
                    <div className="space-y-2 text-sm">
                        {(persistedResult?.imported_at || displayResult) && (
                            <div className="flex items-center justify-between">
                                <span>Last imported:</span>
                                <TZLabel time={persistedResult?.imported_at || new Date().toISOString()} />
                            </div>
                        )}
                        <div className="flex items-center justify-between">
                            <span>Categories imported:</span>
                            <LemonTag>
                                {displayResult?.categories_created ?? persistedResult?.categories_created ?? 0}
                            </LemonTag>
                        </div>
                        <div className="flex items-center justify-between">
                            <span>Globally unsubscribed users:</span>
                            <LemonTag>
                                {(
                                    displayResult?.globally_unsubscribed_count ??
                                    persistedResult?.globally_unsubscribed_count ??
                                    0
                                ).toLocaleString()}
                            </LemonTag>
                        </div>
                    </div>
                </>
            )}

            {/* API key */}
            {hasStoredKey ? (
                <>
                    <div className="space-y-2">
                        <label className="LemonLabel">Customer.io App API Key</label>
                        <LemonInput
                            value="••••••••••••••••"
                            disabledReason="Can't be changed"
                            suffix={
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    status="danger"
                                    tooltip="Remove stored API key"
                                    onClick={removeAppConfig}
                                    loading={isRemovingAppConfig}
                                    icon={<IconTrash className="text-danger" />}
                                />
                            }
                        />
                    </div>
                    <p className="text-sm text-muted">Safe to rerun, existing categories and users will be updated.</p>
                </>
            ) : (
                <Form logic={customerIOImportLogic} formKey="importForm" enableFormOnSubmit>
                    <div className="space-y-4">
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
                            You can generate an App API key in Customer.io under Settings → Account Settings → API
                            Credentials.
                        </div>
                    </div>
                </Form>
            )}

            {/* Action button */}
            <div className="flex justify-end">
                {hasStoredKey ? (
                    <LemonButton type="primary" onClick={rerunImport}>
                        Run again
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="primary"
                        onClick={submitImportForm}
                        disabledReason={!importForm.app_api_key ? 'Enter your API key' : undefined}
                    >
                        Start import
                    </LemonButton>
                )}
            </div>
        </div>
    )
}

function Step2Content(): JSX.Element {
    const { csvFile, csvProgress, isUploadingCSV, syncConfig } = useValues(customerIOImportLogic)
    const { setCSVFile, uploadCSV } = useActions(customerIOImportLogic)
    const persistedCSVResult = !csvProgress ? syncConfig?.csv_import_result : null

    const renderFailedImports = (failed: CSVImportProgress['failed_imports']): JSX.Element | null => {
        if (!failed || failed.length === 0) {
            return null
        }
        return (
            <LemonCollapse
                className="mt-4"
                panels={[
                    {
                        key: 'failed-imports',
                        header: <div className="font-semibold text-sm">Failed imports ({failed.length})</div>,
                        content: (
                            <div className="max-h-32 overflow-y-auto bg-bg-light rounded p-2 text-xs font-mono">
                                {failed.slice(0, 100).map((item, idx) => (
                                    <div key={idx} className="py-0.5">
                                        {item.email}: {item.error}
                                    </div>
                                ))}
                                {failed.length > 100 && (
                                    <div className="text-muted-alt mt-2">... and {failed.length - 100} more</div>
                                )}
                            </div>
                        ),
                    },
                ]}
                defaultActiveKeys={[]}
            />
        )
    }

    if (isUploadingCSV && !csvProgress) {
        return (
            <div className="text-center py-8">
                <Spinner className="text-3xl mb-4" />
                <div className="text-lg font-semibold mb-2">Processing CSV...</div>
                <div className="text-sm text-muted-alt">This may take a moment for large files.</div>
            </div>
        )
    }

    if (csvProgress?.status === 'completed') {
        return (
            <div className="space-y-4">
                <LemonBanner type="success">
                    <span className="font-semibold">CSV import complete</span>
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
                </div>
                {renderFailedImports(csvProgress.failed_imports)}
            </div>
        )
    }

    const csvFailed = csvProgress?.status === 'failed' || persistedCSVResult?.status === 'failed'
    const csvFailureDetail = csvProgress?.details || persistedCSVResult?.error

    if (csvFailed) {
        return (
            <LemonBanner type="error">CSV import failed{csvFailureDetail ? `: ${csvFailureDetail}` : ''}</LemonBanner>
        )
    }

    return (
        <div className="space-y-4">
            <p className="text-sm text-muted">
                Export a CSV from Customer.io containing users with subscription preferences. This is not supported via
                the API. You can upload multiple times to update existing users.
                <br />
                <Link
                    to="https://posthog.com/docs/workflows/import-customerio-optouts"
                    target="_blank"
                    className="text-primary"
                >
                    View instructions
                </Link>
            </p>
            <div>
                {!csvFile ? (
                    <LemonFileInput
                        accept=".csv"
                        multiple={false}
                        value={[]}
                        onChange={(files) => setCSVFile(files[0] || null)}
                        showUploadedFiles={false}
                        callToAction={
                            <div className="border-2 border-dashed border-border rounded-lg p-4 text-center hover:border-primary-light transition-colors cursor-pointer w-full">
                                <div className="text-sm text-muted">Drop your CSV file here or click to browse</div>
                                <div className="text-xs text-muted-alt mt-1">Accepts .csv files only</div>
                            </div>
                        }
                    />
                ) : (
                    <div className="border-2 border-dashed border-border rounded-lg p-3 w-full">
                        <div className="flex items-center justify-between">
                            <div>
                                <div className="font-medium text-sm">{csvFile.name}</div>
                                <div className="text-xs text-muted mt-1">
                                    Size: {(csvFile.size / (1024 * 1024)).toFixed(2)}MB
                                </div>
                            </div>
                            <LemonButton size="small" type="secondary" onClick={() => setCSVFile(null)}>
                                Remove
                            </LemonButton>
                        </div>
                    </div>
                )}
            </div>
            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    onClick={uploadCSV}
                    loading={isUploadingCSV}
                    disabledReason={!csvFile ? 'Please select a CSV file' : undefined}
                >
                    Upload & process CSV
                </LemonButton>
            </div>
        </div>
    )
}

export function CustomerIOImportModal(): JSX.Element {
    const { isImportModalOpen, stepCompletion, syncConfigLoading } = useValues(customerIOImportLogic)
    const { closeImportModal } = useActions(customerIOImportLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)

    return (
        <LemonModal
            title="Customer.io integration"
            description="Import categories and unsubscribed users from Customer.io."
            isOpen={isImportModalOpen}
            onClose={closeImportModal}
            width={640}
        >
            {isAdminOrOwner === false ? (
                <AccessDenied object="Customer.io integration" inline />
            ) : syncConfigLoading ? (
                <div className="flex justify-center py-8">
                    <Spinner className="text-3xl" />
                </div>
            ) : (
                <div className="space-y-4">
                    <LemonBanner type="info">
                        <span>
                            Check our{' '}
                            <Link to="https://posthog.com/docs/workflows/import-customerio-optouts" target="_blank">
                                Customer.io import guide
                            </Link>{' '}
                            for detailed instructions.
                        </span>
                    </LemonBanner>
                    <LemonCollapse
                        defaultActiveKey={!stepCompletion.step1 ? 'step1' : !stepCompletion.step2 ? 'step2' : undefined}
                        panels={[
                            {
                                key: 'step1',
                                header: (
                                    <div className="flex items-center justify-between w-full">
                                        <span>1. Import categories & global opt-outs</span>
                                        <StepBadge status={stepCompletion.step1} />
                                    </div>
                                ),
                                content: <Step1Content />,
                            },
                            {
                                key: 'step2',
                                header: (
                                    <div className="flex items-center justify-between w-full">
                                        <span>2. Upload opt-out preferences CSV</span>
                                        <StepBadge status={stepCompletion.step2} />
                                    </div>
                                ),
                                content: <Step2Content />,
                            },
                        ]}
                    />
                </div>
            )}
        </LemonModal>
    )
}
