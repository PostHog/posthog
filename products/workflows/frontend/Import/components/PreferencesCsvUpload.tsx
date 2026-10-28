import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCollapse, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'

import { CSVImportProgress, customerIOImportLogic } from '../customerIOImportLogic'

export function PreferencesCsvUpload(): JSX.Element {
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
                    data-attr="customerio-preferences-csv-upload"
                    loading={isUploadingCSV}
                    disabledReason={!csvFile ? 'Please select a CSV file' : undefined}
                >
                    Upload & process CSV
                </LemonButton>
            </div>
        </div>
    )
}
