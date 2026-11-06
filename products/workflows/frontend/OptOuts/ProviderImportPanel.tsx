import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import type { ReactNode } from 'react'

import { LemonBanner, LemonButton, LemonCheckbox, LemonInput, Link, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ImportProviderOptionApi, ProviderImportRunApi } from 'products/messaging/frontend/generated/api.schemas'

import { providerImportLogic } from './providerImportLogic'
import { ProviderImportRunProgress } from './ProviderImportRunProgress'

function ImportStepPicker({ provider }: { provider: ImportProviderOptionApi }): JSX.Element {
    const { deselectedImportSteps } = useValues(providerImportLogic)
    const { toggleImportStep } = useActions(providerImportLogic)

    return (
        <div className="space-y-2">
            <label className="LemonLabel">What to import</label>
            {provider.steps.map((step) => (
                <div key={step.key}>
                    <LemonCheckbox
                        checked={!deselectedImportSteps.includes(step.key)}
                        onChange={() => toggleImportStep(step.key)}
                        label={step.label}
                        data-attr={`${provider.key}-import-step-${step.key}`}
                    />
                    <div className="text-xs text-secondary ml-6">{step.description}</div>
                </div>
            ))}
        </div>
    )
}

function ImportRunResult({
    run,
    provider,
}: {
    run: ProviderImportRunApi
    provider: ImportProviderOptionApi
}): JSX.Element {
    const { closeImportModal } = useActions(providerImportLogic)

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
            {!provider.retains_credentials && (
                <p className="text-sm text-secondary m-0" data-attr={`${provider.key}-import-key-deleted`}>
                    PostHog deleted your API key when the import ended.
                </p>
            )}
            <ProviderImportRunProgress run={run} onOpenLink={closeImportModal} />
            {run.finished_at && (
                <div className="flex items-center justify-between text-sm">
                    <span>Finished</span>
                    <TZLabel time={run.finished_at} />
                </div>
            )}
            {provider.next_steps.length > 0 && (
                <div className="space-y-2 pt-2" data-attr={`${provider.key}-import-next-steps`}>
                    <label className="LemonLabel">What to do next</label>
                    <ol className="m-0 pl-5 flex flex-col gap-1.5 text-sm list-decimal">
                        {provider.next_steps.map((step) => (
                            <li key={step}>{step}</li>
                        ))}
                    </ol>
                </div>
            )}
        </div>
    )
}

function ApiKeyHelp({ provider }: { provider: ImportProviderOptionApi }): JSX.Element | null {
    if (!provider.api_key_help && !provider.api_key_url) {
        return null
    }
    return (
        <div className="text-xs text-muted-alt mt-2">
            {provider.api_key_help}{' '}
            {provider.api_key_url && (
                <Link to={provider.api_key_url} target="_blank">
                    Create a key
                </Link>
            )}
        </div>
    )
}

export function ProviderImportPanel({
    provider,
    storedKeyField,
    beforeForm,
    apiKeyPlaceholder = 'Enter your API key',
}: {
    provider: ImportProviderOptionApi
    /** Shown instead of the key field when the provider already has a stored key. */
    storedKeyField?: ReactNode
    beforeForm?: ReactNode
    apiKeyPlaceholder?: string
}): JSX.Element {
    const {
        importForm,
        importError,
        importRuns,
        importRunsLoading,
        latestImportRun,
        isImportRunActive,
        selectedImportSteps,
        startedImportRunLoading,
        showImportAgainForm,
    } = useValues(providerImportLogic)
    const { submitImportForm, startImport, setShowImportAgainForm, loadImportRuns } = useActions(providerImportLogic)

    const noStepsReason = selectedImportSteps.length === 0 ? 'Select at least one thing to import' : undefined

    if (importRuns === null && importRunsLoading) {
        return (
            <div className="flex justify-center py-8">
                <Spinner className="text-3xl" />
            </div>
        )
    }

    // Without the history, the form could hide a running import and start a second one.
    if (importRuns === null) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadImportRuns }}>
                Couldn't load your earlier imports.
            </LemonBanner>
        )
    }

    if (latestImportRun && isImportRunActive) {
        return (
            <div className="space-y-4">
                <LemonBanner type="info">
                    The import runs in the background. You can close this window and come back to check on it.
                </LemonBanner>
                <ProviderImportRunProgress run={latestImportRun} />
            </div>
        )
    }

    // A provider without a stored key needs the key typed again, so the result gets the whole window first.
    if (latestImportRun && !provider.retains_credentials && !showImportAgainForm) {
        return (
            <div className="space-y-4">
                <ImportRunResult run={latestImportRun} provider={provider} />
                <div className="flex justify-end">
                    <LemonButton
                        type="secondary"
                        onClick={() => setShowImportAgainForm(true)}
                        data-attr={`${provider.key}-import-again`}
                    >
                        Import again
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            {latestImportRun && provider.retains_credentials ? (
                <ImportRunResult run={latestImportRun} provider={provider} />
            ) : (
                beforeForm
            )}

            {showImportAgainForm && (
                <p className="text-sm text-secondary m-0">
                    Importing again adds what's new. Anything you changed or deleted in PostHog since the last import
                    stays as it is.
                </p>
            )}

            <ImportStepPicker provider={provider} />

            {provider.not_imported && <p className="text-xs text-secondary m-0">{provider.not_imported}</p>}

            {storedKeyField ?? (
                <Form logic={providerImportLogic} formKey="importForm" enableFormOnSubmit>
                    <LemonField name="api_key" label={provider.api_key_label}>
                        <LemonInput
                            placeholder={apiKeyPlaceholder}
                            type="password"
                            data-attr={`${provider.key}-api-key`}
                            autoComplete="off"
                        />
                    </LemonField>
                    <ApiKeyHelp provider={provider} />
                </Form>
            )}

            {importError && (
                <LemonBanner type="error" className="text-sm">
                    {importError}
                </LemonBanner>
            )}

            <div className="flex justify-end gap-2">
                {showImportAgainForm && (
                    <LemonButton type="secondary" onClick={() => setShowImportAgainForm(false)}>
                        Back to results
                    </LemonButton>
                )}
                {storedKeyField ? (
                    <LemonButton
                        type="primary"
                        onClick={() => startImport({ apiKey: null })}
                        loading={startedImportRunLoading}
                        disabledReason={noStepsReason}
                        data-attr={`${provider.key}-import-run-again`}
                    >
                        {latestImportRun ? 'Run again' : 'Start import'}
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="primary"
                        onClick={submitImportForm}
                        loading={startedImportRunLoading}
                        disabledReason={!importForm.api_key ? 'Enter your API key' : noStepsReason}
                        data-attr={`${provider.key}-import-start`}
                    >
                        Start import
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
