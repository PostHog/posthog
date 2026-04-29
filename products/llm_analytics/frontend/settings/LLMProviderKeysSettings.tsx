import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { IconKey } from 'lib/lemon-ui/icons'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { LLMProviderIcon, LLM_PROVIDER_SELECT_OPTIONS } from '../LLMProviderIcon'
import {
    AlternativeKey,
    CreateLLMProviderKeyPayload,
    DEFAULT_AZURE_API_VERSION,
    DependentConfigsResponse,
    KeyValidationResult,
    LLMProvider,
    LLMProviderKey,
    LLMProviderKeyState,
    LLM_PROVIDER_LABELS,
    TrialEvaluation,
    UpdateLLMProviderKeyPayload,
    llmProviderKeysLogic,
    sortProviderKeys,
} from './llmProviderKeysLogic'
import { TrialUsageMeterDisplay } from './TrialUsageMeter'

function StateTag({ state, errorMessage }: { state: LLMProviderKeyState; errorMessage: string | null }): JSX.Element {
    const tagProps: { type: 'success' | 'danger' | 'warning' | 'default'; children: string } = {
        type: 'default',
        children: 'Unknown',
    }

    switch (state) {
        case 'ok':
            tagProps.type = 'success'
            tagProps.children = 'Valid'
            break
        case 'invalid':
            tagProps.type = 'danger'
            tagProps.children = 'Invalid'
            break
        case 'error':
            tagProps.type = 'warning'
            tagProps.children = 'Error'
            break
        case 'unknown':
            tagProps.type = 'default'
            tagProps.children = 'Unknown'
            break
    }

    const tag = <LemonTag type={tagProps.type}>{tagProps.children}</LemonTag>

    if (errorMessage && (state === 'invalid' || state === 'error')) {
        return <Tooltip title={errorMessage}>{tag}</Tooltip>
    }

    return tag
}

function formatDate(dateString: string | null): string {
    if (!dateString) {
        return 'Never'
    }
    return new Date(dateString).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
    })
}

function getKeyPlaceholder(provider: LLMProvider): string {
    switch (provider) {
        case 'openai':
            return 'sk-...'
        case 'anthropic':
            return 'sk-ant-...'
        case 'gemini':
            return 'Enter your Gemini API key'
        case 'together_ai':
            return 'Enter your Together AI API key'
        case 'openrouter':
            return 'Enter your OpenRouter API key'
        case 'fireworks':
            return 'Enter your Fireworks API key'
        case 'azure_openai':
            return 'Enter your Azure OpenAI API key'
    }
}

// Azure validation errors can originate from either the endpoint or the API key.
// The backend tells us which via `error_field`; map it to which input this component highlights.
function azureErrorFieldFromResult(result: KeyValidationResult | null | undefined): 'endpoint' | 'key' | null {
    if (!result || result.state === 'ok') {
        return null
    }
    return result.error_field === 'azure_endpoint' ? 'endpoint' : 'key'
}

function KeyValidationStatus({
    result,
    isValidating,
    provider,
    suppressError = false,
}: {
    result: KeyValidationResult | null
    isValidating: boolean
    provider: LLMProvider
    suppressError?: boolean
}): JSX.Element | null {
    if (isValidating) {
        return <p className="text-xs text-muted mt-1">Validating key...</p>
    }

    const bullets = (
        <ul className="text-xs text-muted mt-1 list-disc pl-4 space-y-0.5">
            <li>Your key will be encrypted and stored securely</li>
            <li>You pay {LLM_PROVIDER_LABELS[provider]} directly for model usage</li>
            <li>Each evaluation counts as an LLM analytics event</li>
        </ul>
    )

    if (!result) {
        return bullets
    }

    if (result.state === 'ok') {
        return <p className="text-xs text-success mt-1">Key validated successfully</p>
    }

    return (
        <>
            {bullets}
            {!suppressError && (
                <p className="text-xs text-danger mt-1">{result.error_message || 'Key validation failed'}</p>
            )}
        </>
    )
}

function AddKeyModal({ restrictionReason }: { restrictionReason: string | null }): JSX.Element {
    const { newKeyModalOpen, providerKeysLoading, preValidationResult, preValidationResultLoading, evaluationConfig } =
        useValues(llmProviderKeysLogic)
    const { setNewKeyModalOpen, createProviderKey, preValidateKey, clearPreValidation } =
        useActions(llmProviderKeysLogic)

    const [provider, setProvider] = useState<LLMProvider>('openai')
    const [name, setName] = useState('')
    const [apiKey, setApiKey] = useState('')
    const [azureEndpoint, setAzureEndpoint] = useState('')
    const [apiVersion, setApiVersion] = useState(DEFAULT_AZURE_API_VERSION)
    const [pendingSubmit, setPendingSubmit] = useState(false)

    const isAzure = provider === 'azure_openai'
    const keyValidated = preValidationResult?.state === 'ok'
    const isValid = name.length > 0 && apiKey.length > 0 && (!isAzure || azureEndpoint.length > 0)
    const validationFailed = !!preValidationResult && preValidationResult.state !== 'ok'
    const azureErrorField = isAzure && validationFailed ? azureErrorFieldFromResult(preValidationResult) : null

    // Reset form when modal closes
    useEffect(() => {
        if (!newKeyModalOpen) {
            setProvider('openai')
            setName('')
            setApiKey('')
            setAzureEndpoint('')
            setApiVersion(DEFAULT_AZURE_API_VERSION)
            setPendingSubmit(false)
        }
    }, [newKeyModalOpen])

    // Auto-submit after validation succeeds if submit was pending
    useEffect(() => {
        if (pendingSubmit && preValidationResult && !preValidationResultLoading) {
            setPendingSubmit(false)
            if (preValidationResult.state === 'ok') {
                const payload: CreateLLMProviderKeyPayload = {
                    provider,
                    name,
                    api_key: apiKey,
                    set_as_active: !evaluationConfig?.active_provider_key,
                }
                if (isAzure) {
                    payload.azure_endpoint = azureEndpoint
                    payload.api_version = apiVersion
                }
                createProviderKey({ payload })
            }
        }
    }, [
        pendingSubmit,
        preValidationResult,
        preValidationResultLoading,
        createProviderKey,
        name,
        apiKey,
        provider,
        isAzure,
        azureEndpoint,
        apiVersion,
    ]) // oxlint-disable-line react-hooks/exhaustive-deps

    const handleClose = (): void => {
        setNewKeyModalOpen(false)
        clearPreValidation()
    }

    const handleSubmit = (): void => {
        if (keyValidated) {
            const payload: CreateLLMProviderKeyPayload = {
                provider,
                name,
                api_key: apiKey,
                set_as_active: !evaluationConfig?.active_provider_key,
            }
            if (isAzure) {
                payload.azure_endpoint = azureEndpoint
                payload.api_version = apiVersion
            }
            createProviderKey({ payload })
        } else if (apiKey.length > 0) {
            setPendingSubmit(true)
            preValidateKey({
                apiKey,
                provider,
                ...(isAzure ? { azure_endpoint: azureEndpoint, api_version: apiVersion } : {}),
            })
        }
    }

    const handleApiKeyBlur = (): void => {
        if (apiKey.length > 0 && !preValidationResult) {
            preValidateKey({
                apiKey,
                provider,
                ...(isAzure ? { azure_endpoint: azureEndpoint, api_version: apiVersion } : {}),
            })
        }
    }

    const handleApiKeyChange = (value: string): void => {
        setApiKey(value)
        if (preValidationResult) {
            clearPreValidation()
        }
    }

    const handleProviderChange = (value: LLMProvider): void => {
        setProvider(value)
        setApiKey('')
        setAzureEndpoint('')
        setApiVersion(DEFAULT_AZURE_API_VERSION)
        clearPreValidation()
    }

    return (
        <LemonModal
            isOpen={newKeyModalOpen}
            onClose={handleClose}
            title="Add API key"
            width={480}
            footer={
                <>
                    <LemonButton type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={providerKeysLoading}
                        disabled={!isValid}
                        disabledReason={restrictionReason}
                    >
                        Add key
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="text-sm font-medium">Provider</label>
                    <LemonSelect
                        value={provider}
                        onChange={handleProviderChange}
                        options={LLM_PROVIDER_SELECT_OPTIONS}
                        className="mt-1"
                        fullWidth
                    />
                </div>
                {isAzure && (
                    <>
                        <div>
                            <label className="text-sm font-medium">Azure endpoint</label>
                            <LemonInput
                                value={azureEndpoint}
                                onChange={setAzureEndpoint}
                                placeholder="https://my-resource.openai.azure.com/"
                                className="mt-1"
                                fullWidth
                                status={azureErrorField === 'endpoint' ? 'danger' : undefined}
                            />
                            {azureErrorField === 'endpoint' ? (
                                <p className="text-xs text-danger mt-1">
                                    {preValidationResult?.error_message || 'Invalid Azure endpoint'}
                                </p>
                            ) : (
                                <p className="text-xs text-muted mt-1">
                                    The endpoint URL of your Azure OpenAI resource
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="text-sm font-medium">API version</label>
                            <LemonInput
                                value={apiVersion}
                                onChange={setApiVersion}
                                placeholder={DEFAULT_AZURE_API_VERSION}
                                className="mt-1"
                                fullWidth
                            />
                            <p className="text-xs text-muted mt-1">
                                Azure OpenAI API version (defaults to {DEFAULT_AZURE_API_VERSION})
                            </p>
                        </div>
                    </>
                )}
                <div>
                    <label className="text-sm font-medium">Name</label>
                    <LemonInput
                        value={name}
                        onChange={setName}
                        placeholder="e.g. Production key"
                        className="mt-1"
                        fullWidth
                    />
                    <p className="text-xs text-muted mt-1">A friendly name to identify this key</p>
                </div>
                <div>
                    <label className="text-sm font-medium">API key</label>
                    <LemonInput
                        value={apiKey}
                        onChange={handleApiKeyChange}
                        onBlur={handleApiKeyBlur}
                        placeholder={getKeyPlaceholder(provider)}
                        type="password"
                        autoComplete="off"
                        className="mt-1"
                        fullWidth
                        status={validationFailed && (!isAzure || azureErrorField === 'key') ? 'danger' : undefined}
                    />
                    <KeyValidationStatus
                        result={preValidationResult}
                        isValidating={preValidationResultLoading}
                        provider={provider}
                        suppressError={azureErrorField === 'endpoint'}
                    />
                </div>
            </div>
        </LemonModal>
    )
}

function EditKeyModal({
    keyToEdit,
    restrictionReason,
}: {
    keyToEdit: LLMProviderKey
    restrictionReason: string | null
}): JSX.Element {
    const { providerKeysLoading, preValidationResult, preValidationResultLoading } = useValues(llmProviderKeysLogic)
    const { setEditingKey, updateProviderKey, preValidateKey, clearPreValidation } = useActions(llmProviderKeysLogic)
    const isAzureEdit = keyToEdit.provider === 'azure_openai'

    const [name, setName] = useState(keyToEdit.name)
    const [apiKey, setApiKey] = useState('')
    const [azureEndpoint, setAzureEndpoint] = useState(keyToEdit.azure_endpoint_display ?? '')
    const [apiVersion, setApiVersion] = useState(keyToEdit.api_version_display ?? DEFAULT_AZURE_API_VERSION)

    const handleClose = (): void => {
        setEditingKey(null)
        clearPreValidation()
    }

    const handleSubmit = (): void => {
        const payload: UpdateLLMProviderKeyPayload = {}
        if (name !== keyToEdit.name) {
            payload.name = name
        }
        if (apiKey.length > 0) {
            payload.api_key = apiKey
        }
        if (isAzureEdit) {
            if (azureEndpoint !== (keyToEdit.azure_endpoint_display ?? '')) {
                payload.azure_endpoint = azureEndpoint
            }
            if (apiVersion !== (keyToEdit.api_version_display ?? DEFAULT_AZURE_API_VERSION)) {
                payload.api_version = apiVersion
            }
        }
        updateProviderKey({ id: keyToEdit.id, payload })
    }

    const handleApiKeyBlur = (): void => {
        if (apiKey.length > 0) {
            preValidateKey({
                apiKey,
                provider: keyToEdit.provider,
                ...(isAzureEdit ? { azure_endpoint: azureEndpoint, api_version: apiVersion } : {}),
            })
        }
    }

    const handleApiKeyChange = (value: string): void => {
        setApiKey(value)
        if (preValidationResult) {
            clearPreValidation()
        }
    }

    const keyValidated = apiKey.length === 0 || preValidationResult?.state === 'ok'
    const isValid = name.length > 0 && keyValidated
    const validationFailed = !!preValidationResult && preValidationResult.state !== 'ok'
    const azureErrorField = isAzureEdit && validationFailed ? azureErrorFieldFromResult(preValidationResult) : null

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title="Edit API key"
            footer={
                <>
                    <LemonButton type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={providerKeysLoading}
                        disabled={!isValid}
                        disabledReason={restrictionReason}
                    >
                        Save changes
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="text-sm font-medium">Provider</label>
                    <div className="mt-1 flex items-center gap-1.5">
                        <LLMProviderIcon provider={keyToEdit.provider} />
                        <span>{LLM_PROVIDER_LABELS[keyToEdit.provider]}</span>
                    </div>
                </div>
                {isAzureEdit && (
                    <>
                        <div>
                            <label className="text-sm font-medium">Azure endpoint</label>
                            <LemonInput
                                value={azureEndpoint}
                                onChange={setAzureEndpoint}
                                placeholder="https://my-resource.openai.azure.com/"
                                className="mt-1"
                                fullWidth
                                status={azureErrorField === 'endpoint' ? 'danger' : undefined}
                            />
                            {azureErrorField === 'endpoint' && (
                                <p className="text-xs text-danger mt-1">
                                    {preValidationResult?.error_message || 'Invalid Azure endpoint'}
                                </p>
                            )}
                        </div>
                        <div>
                            <label className="text-sm font-medium">API version</label>
                            <LemonInput
                                value={apiVersion}
                                onChange={setApiVersion}
                                placeholder={DEFAULT_AZURE_API_VERSION}
                                className="mt-1"
                                fullWidth
                            />
                        </div>
                    </>
                )}
                <div>
                    <label className="text-sm font-medium">Name</label>
                    <LemonInput value={name} onChange={setName} className="mt-1" fullWidth />
                </div>
                <div>
                    <label className="text-sm font-medium">API key</label>
                    <LemonInput
                        value={apiKey}
                        onChange={handleApiKeyChange}
                        onBlur={handleApiKeyBlur}
                        placeholder={`Leave empty to keep current (${keyToEdit.api_key_masked})`}
                        type="password"
                        autoComplete="off"
                        className="mt-1"
                        fullWidth
                        status={validationFailed && (!isAzureEdit || azureErrorField === 'key') ? 'danger' : undefined}
                    />
                    {apiKey.length > 0 ? (
                        <KeyValidationStatus
                            result={preValidationResult}
                            isValidating={preValidationResultLoading}
                            provider={keyToEdit.provider}
                            suppressError={azureErrorField === 'endpoint'}
                        />
                    ) : (
                        <p className="text-xs text-muted mt-1">Leave empty to keep the current key</p>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}

function DeleteKeyModal({
    keyToDelete,
    dependentConfigs,
    dependentConfigsLoading,
    restrictionReason,
}: {
    keyToDelete: LLMProviderKey
    dependentConfigs: DependentConfigsResponse | null
    dependentConfigsLoading: boolean
    restrictionReason: string | null
}): JSX.Element {
    const { providerKeysLoading } = useValues(llmProviderKeysLogic)
    const { setKeyToDelete, confirmDelete } = useActions(llmProviderKeysLogic)
    const [replacementKeyId, setReplacementKeyId] = useState<string | undefined>(undefined)

    const hasEvaluations = (dependentConfigs?.evaluations.length ?? 0) > 0
    const hasAlternatives = (dependentConfigs?.alternative_keys.length ?? 0) > 0

    const firstAlternativeKeyId = dependentConfigs?.alternative_keys[0]?.id
    useEffect(() => {
        if (hasAlternatives && firstAlternativeKeyId) {
            setReplacementKeyId(firstAlternativeKeyId)
        }
    }, [hasAlternatives, firstAlternativeKeyId])

    const handleClose = (): void => {
        setKeyToDelete(null)
    }

    const handleDelete = (): void => {
        confirmDelete(hasEvaluations && hasAlternatives ? replacementKeyId : undefined)
    }

    const replacementOptions =
        dependentConfigs?.alternative_keys.map((key: AlternativeKey) => ({
            value: key.id,
            label: key.name,
        })) ?? []

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title="Delete API key?"
            width={480}
            footer={
                <>
                    <LemonButton type="secondary" onClick={handleClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        onClick={handleDelete}
                        loading={providerKeysLoading}
                        disabled={dependentConfigsLoading}
                        disabledReason={restrictionReason}
                    >
                        Delete key
                    </LemonButton>
                </>
            }
        >
            {dependentConfigsLoading ? (
                <LemonSkeleton className="h-20" />
            ) : (
                <div className="space-y-4">
                    <p>
                        Are you sure you want to delete "<strong>{keyToDelete.name}</strong>"? This cannot be undone.
                    </p>

                    {hasEvaluations && (
                        <div className="bg-bg-light border rounded p-3">
                            <p className="font-medium mb-2">
                                {dependentConfigs!.evaluations.length} evaluation
                                {dependentConfigs!.evaluations.length === 1 ? '' : 's'} using this key:
                            </p>
                            <ul className="list-disc pl-4 text-sm text-muted space-y-1">
                                {dependentConfigs!.evaluations.map((evaluation) => (
                                    <li key={evaluation.id}>{evaluation.name}</li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {hasEvaluations && hasAlternatives && (
                        <div>
                            <label className="text-sm font-medium">Replace with another key</label>
                            <LemonSelect
                                value={replacementKeyId}
                                onChange={setReplacementKeyId}
                                options={replacementOptions}
                                className="mt-1"
                                fullWidth
                            />
                            <p className="text-xs text-muted mt-1">
                                The selected key will be used by evaluations that currently use this key.
                            </p>
                        </div>
                    )}

                    {hasEvaluations && !hasAlternatives && (
                        <div className="bg-warning-highlight border border-warning rounded p-3">
                            <p className="text-sm">
                                <strong>No replacement keys available.</strong> These evaluations will be disabled after
                                deletion.
                            </p>
                        </div>
                    )}
                </div>
            )}
        </LemonModal>
    )
}

function AssignKeyModal(): JSX.Element | null {
    const { newlyCreatedKey, trialEvaluations, trialEvaluationsLoading } = useValues(llmProviderKeysLogic)
    const { confirmAssignKey, dismissAssignKey } = useActions(llmProviderKeysLogic)

    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
    const [enableAfterAssign, setEnableAfterAssign] = useState(true)

    const hasDisabledEvals = trialEvaluations.some((e: TrialEvaluation) => !e.enabled)
    const isOpen = newlyCreatedKey !== null && !trialEvaluationsLoading && trialEvaluations.length > 0

    // Select all by default when modal opens
    useEffect(() => {
        if (isOpen) {
            setSelectedIds(new Set(trialEvaluations.map((e: TrialEvaluation) => e.id)))
            setEnableAfterAssign(true)
        }
    }, [isOpen]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (!newlyCreatedKey) {
        return null
    }

    // If no trial evals found after loading, auto-dismiss
    if (!trialEvaluationsLoading && trialEvaluations.length === 0) {
        return null
    }

    const toggleEval = (id: string): void => {
        setSelectedIds((prev) => {
            const next = new Set(prev)
            if (next.has(id)) {
                next.delete(id)
            } else {
                next.add(id)
            }
            return next
        })
    }

    const providerLabel = LLM_PROVIDER_LABELS[newlyCreatedKey.provider] || newlyCreatedKey.provider

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={dismissAssignKey}
            title={`Apply "${newlyCreatedKey.name}" to existing evaluations?`}
            width={520}
            footer={
                <>
                    <LemonButton type="secondary" onClick={dismissAssignKey}>
                        Skip
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabled={selectedIds.size === 0}
                        onClick={() => confirmAssignKey(Array.from(selectedIds), enableAfterAssign && hasDisabledEvals)}
                    >
                        Apply key
                        {selectedIds.size > 0
                            ? ` to ${selectedIds.size} evaluation${selectedIds.size !== 1 ? 's' : ''}`
                            : ''}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-3">
                <p className="text-sm text-muted">
                    The following evaluations are using {providerLabel} trial credits. Select which ones should use your
                    new key instead.
                </p>
                <div className="border rounded divide-y">
                    {trialEvaluations.map((evaluation: TrialEvaluation) => (
                        <label
                            key={evaluation.id}
                            className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-bg-light"
                        >
                            <LemonCheckbox
                                checked={selectedIds.has(evaluation.id)}
                                onChange={() => toggleEval(evaluation.id)}
                            />
                            <span className="flex-1 text-sm">{evaluation.name}</span>
                            {!evaluation.enabled && (
                                <LemonTag type="default" size="small">
                                    Disabled
                                </LemonTag>
                            )}
                        </label>
                    ))}
                </div>
                {hasDisabledEvals && (
                    <label className="flex items-center gap-2 cursor-pointer">
                        <LemonCheckbox checked={enableAfterAssign} onChange={setEnableAfterAssign} />
                        <span className="text-sm">Also re-enable disabled evaluations</span>
                    </label>
                )}
            </div>
        </LemonModal>
    )
}

export function LLMProviderKeysSettings(): JSX.Element {
    const {
        providerKeys,
        providerKeysLoading,
        evaluationConfig,
        evaluationConfigLoading,
        editingKey,
        validatingKeyId,
        keyToDelete,
        dependentConfigs,
        dependentConfigsLoading,
    } = useValues(llmProviderKeysLogic)
    const { setNewKeyModalOpen, validateProviderKey, setEditingKey, setKeyToDelete } = useActions(llmProviderKeysLogic)
    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const columns: LemonTableColumns<LLMProviderKey> = [
        {
            title: 'Name',
            key: 'name',
            render: (_, key) => (
                <div className="flex items-center gap-2">
                    <IconKey className="text-muted" />
                    <div>
                        <span className="font-medium">{key.name}</span>
                        {key.error_message && (key.state === 'invalid' || key.state === 'error') && (
                            <div className="text-xs text-danger mt-0.5">{key.error_message}</div>
                        )}
                    </div>
                </div>
            ),
        },
        {
            title: 'Provider',
            key: 'provider',
            render: (_, key) => (
                <div className="flex items-center gap-1.5">
                    <LLMProviderIcon provider={key.provider} />
                    <span>{LLM_PROVIDER_LABELS[key.provider]}</span>
                </div>
            ),
        },
        {
            title: 'Key',
            key: 'api_key_masked',
            render: (_, key) => <code className="text-sm bg-bg-light px-2 py-1 rounded">{key.api_key_masked}</code>,
        },
        {
            title: 'State',
            key: 'state',
            render: (_, key) => <StateTag state={key.state} errorMessage={key.error_message} />,
        },
        {
            title: 'Last used',
            key: 'last_used_at',
            render: (_, key) => <span className="text-muted text-sm">{formatDate(key.last_used_at)}</span>,
        },
        {
            title: 'Created',
            key: 'created_at',
            render: (_, key) => (
                <div className="text-sm">
                    <div>{formatDate(key.created_at)}</div>
                    {key.created_by && (
                        <div className="text-muted text-xs">by {key.created_by.first_name || key.created_by.email}</div>
                    )}
                </div>
            ),
        },
        {
            title: '',
            key: 'actions',
            width: 150,
            render: (_, key) => (
                <div className="flex gap-1">
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconRefresh />}
                        loading={validatingKeyId === key.id}
                        onClick={() => validateProviderKey({ id: key.id })}
                        disabledReason={restrictionReason}
                    >
                        Validate
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => setEditingKey(key)}
                        disabledReason={restrictionReason}
                    >
                        Edit
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="secondary"
                        status="danger"
                        icon={<IconTrash />}
                        onClick={() => setKeyToDelete(key)}
                        disabledReason={restrictionReason}
                    />
                </div>
            ),
        },
    ]

    const isLoading = (providerKeysLoading || evaluationConfigLoading) && providerKeys.length === 0

    return (
        <>
            <div className="space-y-6">
                {isLoading ? (
                    <LemonSkeleton className="w-full h-64" />
                ) : (
                    <>
                        <div className="flex justify-between items-start">
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                onClick={() => setNewKeyModalOpen(true)}
                                disabledReason={restrictionReason}
                            >
                                Add API key
                            </LemonButton>
                        </div>

                        {evaluationConfig && !evaluationConfig.active_provider_key && (
                            <TrialUsageMeterDisplay evaluationConfig={evaluationConfig} />
                        )}

                        {providerKeys.length === 0 ? (
                            <div className="border rounded-lg p-8 flex flex-col items-center">
                                <IconKey className="text-muted text-4xl mb-4" />
                                <h3 className="font-semibold mb-2">No API keys configured</h3>
                                <p className="text-muted mb-4 text-center">
                                    Add your API key for LLM analytics features with your own account.
                                    <br />
                                    Used for evaluations and the playground.
                                </p>
                                <LemonButton
                                    type="primary"
                                    icon={<IconPlus />}
                                    onClick={() => setNewKeyModalOpen(true)}
                                    disabledReason={restrictionReason}
                                >
                                    Add API key
                                </LemonButton>
                            </div>
                        ) : (
                            <LemonTable
                                columns={columns}
                                dataSource={sortProviderKeys(providerKeys)}
                                loading={providerKeysLoading}
                                rowKey="id"
                            />
                        )}
                    </>
                )}
            </div>
            <AddKeyModal restrictionReason={restrictionReason} />
            <AssignKeyModal />
            {editingKey && <EditKeyModal keyToEdit={editingKey} restrictionReason={restrictionReason} />}
            {keyToDelete && (
                <DeleteKeyModal
                    keyToDelete={keyToDelete}
                    dependentConfigs={dependentConfigs}
                    dependentConfigsLoading={dependentConfigsLoading}
                    restrictionReason={restrictionReason}
                />
            )}
        </>
    )
}
