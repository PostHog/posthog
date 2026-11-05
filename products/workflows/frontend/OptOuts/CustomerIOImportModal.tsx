import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCopy, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonCollapse,
    LemonInput,
    LemonModal,
    LemonSegmentedButton,
    LemonTag,
    Link,
    Spinner,
} from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { organizationLogic } from 'scenes/organizationLogic'

import type { ProviderImportRunApi } from 'products/messaging/frontend/generated/api.schemas'

import { CSVImportProgress, customerIOImportLogic } from './customerIOImportLogic'
import { CustomerIOImportRunProgress } from './CustomerIOImportRunProgress'

function StepBadge({ status }: { status: 'completed' | 'failed' | false }): JSX.Element | null {
    if (status === 'completed') {
        return <LemonTag type="success">Completed</LemonTag>
    }
    if (status === 'failed') {
        return <LemonTag type="warning">Failed</LemonTag>
    }
    return null
}

function ImportStepPicker(): JSX.Element {
    const { importProviders, importProvidersLoading, importStepOptions, deselectedImportSteps } =
        useValues(customerIOImportLogic)
    const { toggleImportStep, loadImportProviders } = useActions(customerIOImportLogic)

    if (importProviders === null && importProvidersLoading) {
        return <Spinner />
    }
    if (importProviders === null) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadImportProviders }}>
                Couldn't load what you can import.
            </LemonBanner>
        )
    }

    return (
        <div className="space-y-2">
            <label className="LemonLabel">What to import</label>
            {importStepOptions.map((step) => (
                <div key={step.key}>
                    <LemonCheckbox
                        checked={!deselectedImportSteps.includes(step.key)}
                        onChange={() => toggleImportStep(step.key)}
                        label={step.label}
                        data-attr={`customerio-import-step-${step.key}`}
                    />
                    <div className="text-xs text-secondary ml-6">{step.description}</div>
                </div>
            ))}
        </div>
    )
}

function LatestImportRunResult({ run }: { run: ProviderImportRunApi }): JSX.Element {
    return (
        <div className="space-y-3">
            {run.status === 'completed' ? (
                <LemonBanner type="success">
                    <span className="font-semibold">Import finished</span>
                </LemonBanner>
            ) : (
                <LemonBanner type="error">
                    Some steps failed. Run the import again to retry them. Data that already imported isn't duplicated.
                </LemonBanner>
            )}
            <CustomerIOImportRunProgress run={run} />
            {run.finished_at && (
                <div className="flex items-center justify-between text-sm">
                    <span>Finished</span>
                    <TZLabel time={run.finished_at} />
                </div>
            )}
        </div>
    )
}

function LegacyImportResult(): JSX.Element | null {
    const { syncConfig } = useValues(customerIOImportLogic)
    const result = syncConfig?.app_import_result

    if (result?.status === 'failed') {
        return <LemonBanner type="error">Last import failed: {result.error || 'Unknown error'}</LemonBanner>
    }
    if (result?.status !== 'completed') {
        return null
    }
    return (
        <div className="space-y-2 text-sm">
            <LemonBanner type="success">
                <span className="font-semibold">API import complete</span>
            </LemonBanner>
            <div className="flex items-center justify-between">
                <span>Last imported:</span>
                <TZLabel time={result.imported_at} />
            </div>
            <div className="flex items-center justify-between">
                <span>Categories imported:</span>
                <LemonTag>{result.categories_created ?? 0}</LemonTag>
            </div>
            <div className="flex items-center justify-between">
                <span>Globally unsubscribed users:</span>
                <LemonTag>{(result.globally_unsubscribed_count ?? 0).toLocaleString()}</LemonTag>
            </div>
            <div className="flex items-center justify-between">
                <span>Suppressed addresses:</span>
                <LemonTag>{(result.suppressions_imported ?? 0).toLocaleString()}</LemonTag>
            </div>
        </div>
    )
}

function Step1Content(): JSX.Element {
    const {
        importForm,
        importError,
        syncConfig,
        isRemovingAppConfig,
        importRuns,
        importRunsLoading,
        latestImportRun,
        isImportRunActive,
        selectedImportSteps,
        startedImportRunLoading,
    } = useValues(customerIOImportLogic)
    const { submitImportForm, startImport, removeAppConfig } = useActions(customerIOImportLogic)

    const hasStoredKey = syncConfig?.app_integration_id != null
    const noStepsReason = selectedImportSteps.length === 0 ? 'Select at least one thing to import' : undefined

    if (importRuns === null && importRunsLoading) {
        return (
            <div className="flex justify-center py-8">
                <Spinner className="text-3xl" />
            </div>
        )
    }

    if (latestImportRun && isImportRunActive) {
        return (
            <div className="space-y-4">
                <LemonBanner type="info">
                    The import runs in the background. You can close this window and come back to check on it.
                </LemonBanner>
                <CustomerIOImportRunProgress run={latestImportRun} />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            {latestImportRun ? <LatestImportRunResult run={latestImportRun} /> : <LegacyImportResult />}

            <ImportStepPicker />

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
                    <LemonField name="app_api_key" label="Customer.io App API Key">
                        <LemonInput
                            placeholder="Enter your App API key"
                            type="password"
                            data-attr="customerio-api-key"
                            autoComplete="off"
                        />
                    </LemonField>
                    <div className="text-xs text-muted-alt mt-2">
                        You can generate an App API key in Customer.io under Settings → Account Settings → API
                        Credentials.
                    </div>
                </Form>
            )}

            {importError && (
                <LemonBanner type="error" className="text-sm">
                    {importError}
                </LemonBanner>
            )}

            <div className="flex justify-end">
                {hasStoredKey ? (
                    <LemonButton
                        type="primary"
                        onClick={() => startImport({ apiKey: null })}
                        loading={startedImportRunLoading}
                        disabledReason={noStepsReason}
                        data-attr="customerio-import-run-again"
                    >
                        {latestImportRun ? 'Run again' : 'Start import'}
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="primary"
                        onClick={submitImportForm}
                        loading={startedImportRunLoading}
                        disabledReason={!importForm.app_api_key ? 'Enter your API key' : noStepsReason}
                        data-attr="customerio-import-start"
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

function Step3Content(): JSX.Element {
    const { syncConfig, webhookUrl, webhookSigningSecret, isSavingWebhook, webhookError, isRemovingWebhookConfig } =
        useValues(customerIOImportLogic)
    const { setWebhookSigningSecret, saveWebhookConfig, toggleWebhook, removeWebhookConfig } =
        useActions(customerIOImportLogic)

    const webhookEnabled = syncConfig?.webhook_enabled ?? false
    const hasSecret = syncConfig?.has_webhook_secret ?? false

    return (
        <div className="space-y-4">
            <p className="text-sm text-muted">
                Configure Customer.io to send a webhook when a user unsubscribes, so PostHog automatically records the
                opt-out.
            </p>

            {/* Webhook URL */}
            <div className="space-y-2">
                <label className="LemonLabel">Webhook URL</label>
                <div className="flex items-center gap-2">
                    <LemonInput
                        value={webhookUrl}
                        disabledReason="Copy this URL"
                        className="flex-1 font-mono text-xs"
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconCopy />}
                        tooltip="Copy URL"
                        onClick={() => void copyToClipboard(webhookUrl, 'webhook URL')}
                    />
                </div>
                <p className="text-xs text-muted-alt">
                    Paste this URL into Customer.io under Integrations → Add integration → Reporting webhook.
                </p>
            </div>

            {webhookError && (
                <LemonBanner type="error" className="text-sm">
                    {webhookError}
                </LemonBanner>
            )}

            {webhookEnabled && <LemonBanner type="success">Inbound webhook sync is active.</LemonBanner>}

            {/* Signing secret */}
            {hasSecret ? (
                <>
                    <div className="space-y-2">
                        <label className="LemonLabel">Webhook signing secret</label>
                        <LemonInput
                            value="••••••••••••••••"
                            disabledReason="Can't be changed"
                            suffix={
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    status="danger"
                                    tooltip="Remove signing secret"
                                    onClick={removeWebhookConfig}
                                    loading={isRemovingWebhookConfig}
                                    icon={<IconTrash className="text-danger" />}
                                />
                            }
                        />
                    </div>
                    <div className="flex justify-end">
                        {webhookEnabled ? (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                onClick={() => toggleWebhook(false)}
                                loading={isSavingWebhook}
                            >
                                Disable sync
                            </LemonButton>
                        ) : (
                            <LemonButton type="primary" onClick={() => toggleWebhook(true)} loading={isSavingWebhook}>
                                Enable sync
                            </LemonButton>
                        )}
                    </div>
                </>
            ) : (
                <div className="space-y-3">
                    <div className="space-y-2">
                        <label className="LemonLabel">Webhook signing secret</label>
                        <LemonInput
                            value={webhookSigningSecret}
                            onChange={setWebhookSigningSecret}
                            placeholder="Enter your webhook signing secret"
                            type="password"
                            autoComplete="off"
                        />
                        <p className="text-xs text-muted-alt">
                            Find this in Customer.io under Settings → Webhooks → Reporting webhooks → Signing secret.
                        </p>
                    </div>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            onClick={saveWebhookConfig}
                            loading={isSavingWebhook}
                            disabledReason={!webhookSigningSecret ? 'Enter the signing secret' : undefined}
                        >
                            Enable sync
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}

function Step4Content(): JSX.Element {
    const {
        syncConfig,
        trackSiteId,
        trackApiKey,
        trackRegion,
        isSavingTrack,
        trackError,
        isRemovingTrackConfig,
        trackEnabled,
        hasTrackCredentials,
    } = useValues(customerIOImportLogic)
    const { setTrackSiteId, setTrackApiKey, setTrackRegion, saveTrackConfig, toggleTrackSync, removeTrackConfig } =
        useActions(customerIOImportLogic)

    return (
        <div className="space-y-4">
            <p className="text-sm text-muted">
                When users change their preferences on the PostHog-managed page, automatically sync those changes back
                to Customer.io. Only categories imported from Customer.io are synced.
            </p>

            {trackError && (
                <LemonBanner type="error" className="text-sm">
                    {trackError}
                </LemonBanner>
            )}

            {trackEnabled && <LemonBanner type="success">Outbound sync is active.</LemonBanner>}

            {hasTrackCredentials ? (
                <>
                    <div className="space-y-2">
                        <label className="LemonLabel">Track API credentials</label>
                        <LemonInput
                            value="••••••••••••••••"
                            disabledReason="Can't be changed"
                            suffix={
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    status="danger"
                                    tooltip="Remove track integration"
                                    onClick={removeTrackConfig}
                                    loading={isRemovingTrackConfig}
                                    icon={<IconTrash className="text-danger" />}
                                />
                            }
                        />
                    </div>
                    <div className="flex justify-end">
                        {syncConfig?.track_enabled ? (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                onClick={() => toggleTrackSync(false)}
                                loading={isSavingTrack}
                            >
                                Disable sync
                            </LemonButton>
                        ) : (
                            <LemonButton type="primary" onClick={() => toggleTrackSync(true)} loading={isSavingTrack}>
                                Enable sync
                            </LemonButton>
                        )}
                    </div>
                </>
            ) : (
                <div className="space-y-3">
                    <div className="space-y-2">
                        <label className="LemonLabel">Region</label>
                        <LemonSegmentedButton
                            value={trackRegion}
                            onChange={setTrackRegion}
                            options={[
                                { value: 'US', label: 'US', tooltip: 'track.customer.io' },
                                { value: 'EU', label: 'EU', tooltip: 'track-eu.customer.io' },
                            ]}
                            size="small"
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="LemonLabel">Site ID</label>
                        <LemonInput
                            value={trackSiteId}
                            onChange={setTrackSiteId}
                            placeholder="Your Customer.io site ID"
                            autoComplete="off"
                        />
                    </div>
                    <div className="space-y-2">
                        <label className="LemonLabel">Track API key</label>
                        <LemonInput
                            value={trackApiKey}
                            onChange={setTrackApiKey}
                            placeholder="Your Customer.io Track API key"
                            type="password"
                            autoComplete="off"
                        />
                    </div>
                    <p className="text-xs text-muted-alt">
                        Find these in Customer.io under Settings → API and webhook credentials → Track API Keys.
                    </p>
                    <div className="flex justify-end">
                        <LemonButton
                            type="primary"
                            onClick={saveTrackConfig}
                            loading={isSavingTrack}
                            disabledReason={!trackSiteId || !trackApiKey ? 'Enter site ID and API key' : undefined}
                        >
                            Enable sync
                        </LemonButton>
                    </div>
                </div>
            )}
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
            description="Import categories, unsubscribed users and suppressed addresses from Customer.io."
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
                        defaultActiveKey={(['step1', 'step2', 'step3', 'step4'] as const).find(
                            (s) => !stepCompletion[s]
                        )}
                        panels={[
                            {
                                key: 'step1',
                                header: (
                                    <div className="flex items-center justify-between w-full">
                                        <span>1. Import categories, opt-outs & suppressions</span>
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
                            {
                                key: 'step3',
                                header: (
                                    <div className="flex items-center justify-between w-full">
                                        <span>3. Inbound webhook sync</span>
                                        <StepBadge status={stepCompletion.step3} />
                                    </div>
                                ),
                                content: <Step3Content />,
                            },
                            {
                                key: 'step4',
                                header: (
                                    <div className="flex items-center justify-between w-full">
                                        <span>4. Outbound sync to Customer.io</span>
                                        <StepBadge status={stepCompletion.step4} />
                                    </div>
                                ),
                                content: <Step4Content />,
                            },
                        ]}
                    />
                </div>
            )}
        </LemonModal>
    )
}
