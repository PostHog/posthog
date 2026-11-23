import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import type { ReactNode } from 'react'

import { IconCheckCircle, IconInfo } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonSelect,
    LemonTag,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ImportProviderOptionApi, ProviderImportRunApi } from 'products/messaging/frontend/generated/api.schemas'

import { joinWithAnd, providerImportLogic } from './providerImportLogic'
import { ProviderImportRunProgress } from './ProviderImportRunProgress'

// The first sentence fits on a line or two, so the key field and Start button stay in view. The rest goes in a tooltip.
function splitDescription(description: string): { summary: string; detail: string } {
    const end = description.search(/\.\s/)
    if (end === -1) {
        return { summary: description, detail: '' }
    }
    return { summary: description.slice(0, end + 1), detail: description.slice(end + 2).trim() }
}

function ImportStepPicker({ provider }: { provider: ImportProviderOptionApi }): JSX.Element {
    const { deselectedImportSteps, unmetStepNeeds } = useValues(providerImportLogic)
    const { toggleImportStep } = useActions(providerImportLogic)

    return (
        <div className="space-y-2">
            <label className="LemonLabel">What to import</label>
            {provider.steps.map((step) => {
                const { summary, detail } = splitDescription(step.description)
                const unmet = unmetStepNeeds[step.key]
                return (
                    <div key={step.key}>
                        <div className="flex items-center gap-2">
                            <LemonCheckbox
                                checked={!deselectedImportSteps.includes(step.key)}
                                onChange={() => toggleImportStep(step.key)}
                                label={step.label}
                                data-attr={`${provider.key}-import-step-${step.key}`}
                            />
                            {step.counts_as_events && (
                                <Tooltip title="Each person this step adds or updates counts as one event on your bill.">
                                    <LemonTag
                                        type="caution"
                                        data-attr={`${provider.key}-import-step-${step.key}-billed`}
                                    >
                                        Billed as events
                                    </LemonTag>
                                </Tooltip>
                            )}
                        </div>
                        <div className="text-xs text-secondary ml-6">
                            {summary}
                            {detail && (
                                <Tooltip title={detail}>
                                    <span
                                        tabIndex={0}
                                        aria-label={detail}
                                        className="ml-1 inline-flex align-text-bottom"
                                    >
                                        <IconInfo className="text-sm text-muted" />
                                    </span>
                                </Tooltip>
                            )}
                        </div>
                        {unmet && (
                            <div
                                className="text-xs text-warning ml-6"
                                data-attr={`${provider.key}-import-step-${step.key}-needs`}
                            >
                                Also select {joinWithAnd(unmet)}, or this step can't run.
                            </div>
                        )}
                    </div>
                )
            })}
        </div>
    )
}

function ImportSettingsPicker({ provider }: { provider: ImportProviderOptionApi }): JSX.Element | null {
    const { importSettings } = useValues(providerImportLogic)
    const { setImportSetting } = useActions(providerImportLogic)

    if (!provider.settings?.length) {
        return null
    }
    return (
        <div className="space-y-3">
            {provider.settings.map((setting) => (
                <div key={setting.key} className="space-y-1">
                    <label className="LemonLabel">{setting.label}</label>
                    <LemonSelect
                        fullWidth
                        placeholder="Choose one"
                        value={importSettings[setting.key] ?? null}
                        onChange={(value) => value && setImportSetting(setting.key, value)}
                        options={setting.choices.map((choice) => ({ value: choice.value, label: choice.label }))}
                        data-attr={`${provider.key}-import-setting-${setting.key}`}
                    />
                    <div className="text-xs text-secondary">{setting.help}</div>
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
                <LemonBanner type="success" icon={<IconCheckCircle className="LemonBanner__icon hidden @md:!block" />}>
                    <span className="font-semibold">Import finished</span>
                </LemonBanner>
            ) : (
                <LemonBanner type="error">
                    Some steps failed. Run the import again to retry them. Data that already imported isn't duplicated.
                </LemonBanner>
            )}
            {!provider.retains_credentials && (
                <div className="text-sm text-secondary" data-attr={`${provider.key}-import-key-deleted`}>
                    PostHog deleted your {keyNoun(provider)} when the import ended.
                </div>
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

// Some tools call their key a token, so the field's prompts use the tool's own word.
function keyNoun(provider: ImportProviderOptionApi): 'token' | 'API key' {
    return /token/i.test(provider.api_key_label) ? 'token' : 'API key'
}

// Catches a value copied with extra characters before Start sends it to the tool.
// The hint waits for `length` characters, because a shorter value is usually still being typed.
const API_KEY_FORMATS: Record<string, { pattern: RegExp; length: number; hint: string }> = {
    postmark: {
        length: 36,
        pattern: /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
        hint: "This doesn't look like a Postmark token, which has 36 characters in five groups, like 1b2c3d4e-0000-0000-0000-123456789abc. Check that you copied the whole token and nothing else.",
    },
}

function ApiKeyFormatHint({ provider }: { provider: ImportProviderOptionApi }): JSX.Element | null {
    const { importForm } = useValues(providerImportLogic)
    const format = API_KEY_FORMATS[provider.key]
    const value = importForm.api_key.trim()
    if (!format || value.length < format.length || format.pattern.test(value)) {
        return null
    }
    return (
        <div className="text-xs text-warning mt-1" data-attr={`${provider.key}-api-key-format-hint`}>
            {format.hint}
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
                    {keyNoun(provider) === 'token' ? 'Create a token' : 'Create a key'}
                </Link>
            )}
        </div>
    )
}

function ImportStartButton({
    provider,
    hasStoredKey,
}: {
    provider: ImportProviderOptionApi
    hasStoredKey: boolean
}): JSX.Element {
    const { importForm, latestImportRun, cannotStartImportReason, startedImportRunLoading } =
        useValues(providerImportLogic)
    const { submitImportForm, startImport } = useActions(providerImportLogic)

    if (hasStoredKey) {
        return (
            <LemonButton
                type="primary"
                onClick={() => startImport({ apiKey: null })}
                loading={startedImportRunLoading}
                disabledReason={cannotStartImportReason}
                data-attr={`${provider.key}-import-run-again`}
            >
                {latestImportRun ? 'Run again' : 'Start import'}
            </LemonButton>
        )
    }
    return (
        <LemonButton
            type="primary"
            onClick={submitImportForm}
            loading={startedImportRunLoading}
            disabledReason={!importForm.api_key.trim() ? `Enter your ${keyNoun(provider)}` : cannotStartImportReason}
            data-attr={`${provider.key}-import-start`}
        >
            Start import
        </LemonButton>
    )
}

// The negative offsets cancel the window's padding, so the pinned bar meets the window's edges.
const PINNED_BAR_CLASSES = 'sticky -bottom-4 -mx-4 -mb-4 border-t bg-surface-primary px-4 pt-3 pb-4'

function ImportForm({
    provider,
    storedKeyField,
    beforeForm,
    apiKeyPlaceholder,
    pinActions,
}: {
    provider: ImportProviderOptionApi
    storedKeyField?: ReactNode
    beforeForm?: ReactNode
    apiKeyPlaceholder?: string
    pinActions: boolean
}): JSX.Element {
    const { importError, latestImportRun, showImportAgainForm } = useValues(providerImportLogic)
    const { setShowImportAgainForm } = useActions(providerImportLogic)

    return (
        <div className="space-y-4">
            {latestImportRun && provider.retains_credentials ? (
                <ImportRunResult run={latestImportRun} provider={provider} />
            ) : (
                beforeForm
            )}

            {showImportAgainForm && (
                <div className="text-sm text-secondary">
                    Importing again adds what's new. Anything you changed or deleted in PostHog since the last import
                    stays as it is.
                </div>
            )}

            <ImportSettingsPicker provider={provider} />

            <ImportStepPicker provider={provider} />

            {provider.not_imported && <div className="text-xs text-secondary">{provider.not_imported}</div>}

            <div className={clsx(pinActions ? ['space-y-3', PINNED_BAR_CLASSES] : 'space-y-4')}>
                {storedKeyField ?? (
                    <Form logic={providerImportLogic} formKey="importForm" enableFormOnSubmit>
                        <LemonField name="api_key" label={provider.api_key_label}>
                            <LemonInput
                                placeholder={apiKeyPlaceholder ?? `Enter your ${keyNoun(provider)}`}
                                type="password"
                                data-attr={`${provider.key}-api-key`}
                                autoComplete="off"
                            />
                        </LemonField>
                        <ApiKeyFormatHint provider={provider} />
                        <ApiKeyHelp provider={provider} />
                    </Form>
                )}

                {importError && (
                    <LemonBanner type="error" className="text-sm">
                        {importError}
                    </LemonBanner>
                )}

                <div className="flex flex-wrap justify-end gap-2">
                    {showImportAgainForm && (
                        <LemonButton type="secondary" onClick={() => setShowImportAgainForm(false)}>
                            Back to results
                        </LemonButton>
                    )}
                    <ImportStartButton provider={provider} hasStoredKey={!!storedKeyField} />
                </div>
            </div>
        </div>
    )
}

export function ProviderImportPanel({
    provider,
    storedKeyField,
    beforeForm,
    apiKeyPlaceholder,
    pinActions = false,
}: {
    provider: ImportProviderOptionApi
    /** Shown instead of the key field when the provider already has a stored key. */
    storedKeyField?: ReactNode
    beforeForm?: ReactNode
    apiKeyPlaceholder?: string
    /** Keeps the key field and Start button in view while the window scrolls. Only for a panel that fills the window. */
    pinActions?: boolean
}): JSX.Element {
    const { importRuns, importRunsLoading, latestImportRun, isImportRunActive, showImportAgainForm } =
        useValues(providerImportLogic)
    const { setShowImportAgainForm, loadImportRuns } = useActions(providerImportLogic)

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
                <div className={clsx('flex justify-end', pinActions && PINNED_BAR_CLASSES)}>
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
        <ImportForm
            provider={provider}
            storedKeyField={storedKeyField}
            beforeForm={beforeForm}
            apiKeyPlaceholder={apiKeyPlaceholder}
            pinActions={pinActions}
        />
    )
}
