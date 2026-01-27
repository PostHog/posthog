import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { IconKey } from 'lib/lemon-ui/icons'

import { TrialUsageMeterDisplay } from './TrialUsageMeter'
import {
    KeyValidationResult,
    LLMProvider,
    LLMProviderKey,
    LLMProviderKeyState,
    LLM_PROVIDER_LABELS,
    llmProviderKeysLogic,
} from './llmProviderKeysLogic'

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
    }
}

function KeyValidationStatus({
    result,
    isValidating,
    provider,
}: {
    result: KeyValidationResult | null
    isValidating: boolean
    provider: LLMProvider
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
            <p className="text-xs text-danger mt-1">{result.error_message || 'Key validation failed'}</p>
        </>
    )
}

function AddKeyModal(): JSX.Element {
    const { newKeyModalOpen, providerKeysLoading, preValidationResult, preValidationResultLoading } =
        useValues(llmProviderKeysLogic)
    const { setNewKeyModalOpen, createProviderKey, preValidateKey, clearPreValidation } =
        useActions(llmProviderKeysLogic)

    const [provider, setProvider] = useState<LLMProvider>('openai')
    const [name, setName] = useState('')
    const [apiKey, setApiKey] = useState('')
    const [pendingSubmit, setPendingSubmit] = useState(false)

    const keyValidated = preValidationResult?.state === 'ok'
    const isValid = name.length > 0 && apiKey.length > 0

    // Reset form when modal closes
    useEffect(() => {
        if (!newKeyModalOpen) {
            setProvider('openai')
            setName('')
            setApiKey('')
            setPendingSubmit(false)
        }
    }, [newKeyModalOpen])

    // Auto-submit after validation succeeds if submit was pending
    useEffect(() => {
        if (pendingSubmit && preValidationResult && !preValidationResultLoading) {
            setPendingSubmit(false)
            if (preValidationResult.state === 'ok') {
                createProviderKey({
                    payload: {
                        provider,
                        name,
                        api_key: apiKey,
                    },
                })
            }
        }
    }, [pendingSubmit, preValidationResult, preValidationResultLoading, createProviderKey, name, apiKey, provider])

    const handleClose = (): void => {
        setNewKeyModalOpen(false)
        clearPreValidation()
    }

    const handleSubmit = (): void => {
        if (keyValidated) {
            createProviderKey({
                payload: {
                    provider,
                    name,
                    api_key: apiKey,
                },
            })
        } else if (apiKey.length > 0) {
            setPendingSubmit(true)
            preValidateKey({ apiKey, provider })
        }
    }

    const handleApiKeyBlur = (): void => {
        if (apiKey.length > 0 && !preValidationResult) {
            preValidateKey({ apiKey, provider })
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
                        options={[
                            { value: 'openai', label: 'OpenAI' },
                            { value: 'anthropic', label: 'Anthropic' },
                            { value: 'gemini', label: 'Google Gemini' },
                        ]}
                        className="mt-1"
                        fullWidth
                    />
                </div>
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
                        status={preValidationResult && preValidationResult.state !== 'ok' ? 'danger' : undefined}
                    />
                    <KeyValidationStatus
                        result={preValidationResult}
                        isValidating={preValidationResultLoading}
                        provider={provider}
                    />
                </div>
            </div>
        </LemonModal>
    )
}

function EditKeyModal({ keyToEdit }: { keyToEdit: LLMProviderKey }): JSX.Element {
    const { providerKeysLoading, preValidationResult, preValidationResultLoading } = useValues(llmProviderKeysLogic)
    const { setEditingKey, updateProviderKey, preValidateKey, clearPreValidation } = useActions(llmProviderKeysLogic)
    const [name, setName] = useState(keyToEdit.name)
    const [apiKey, setApiKey] = useState('')

    const handleClose = (): void => {
        setEditingKey(null)
        clearPreValidation()
    }

    const handleSubmit = (): void => {
        const payload: { name?: string; api_key?: string } = {}
        if (name !== keyToEdit.name) {
            payload.name = name
        }
        if (apiKey.length > 0) {
            payload.api_key = apiKey
        }
        updateProviderKey({ id: keyToEdit.id, payload })
    }

    const handleApiKeyBlur = (): void => {
        if (apiKey.length > 0) {
            preValidateKey({ apiKey, provider: keyToEdit.provider })
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
                    >
                        Save changes
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="text-sm font-medium">Provider</label>
                    <div className="mt-1">
                        <LemonTag type="default">{LLM_PROVIDER_LABELS[keyToEdit.provider]}</LemonTag>
                    </div>
                </div>
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
                        status={preValidationResult && preValidationResult.state !== 'ok' ? 'danger' : undefined}
                    />
                    {apiKey.length > 0 ? (
                        <KeyValidationStatus
                            result={preValidationResult}
                            isValidating={preValidationResultLoading}
                            provider={keyToEdit.provider}
                        />
                    ) : (
                        <p className="text-xs text-muted mt-1">Leave empty to keep the current key</p>
                    )}
                </div>
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
    } = useValues(llmProviderKeysLogic)
    const { setNewKeyModalOpen, deleteProviderKey, validateProviderKey, setEditingKey } =
        useActions(llmProviderKeysLogic)

    const handleDelete = (key: LLMProviderKey): void => {
        LemonDialog.open({
            title: 'Delete API key?',
            description: `Are you sure you want to delete "${key.name}"? This cannot be undone.`,
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteProviderKey({ id: key.id }),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

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
            render: (_, key) => <LemonTag type="default">{LLM_PROVIDER_LABELS[key.provider]}</LemonTag>,
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
                    {key.state !== 'ok' && (
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconRefresh />}
                            loading={validatingKeyId === key.id}
                            onClick={() => validateProviderKey({ id: key.id })}
                        >
                            Validate
                        </LemonButton>
                    )}
                    <LemonButton size="small" type="secondary" onClick={() => setEditingKey(key)}>
                        Edit
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="secondary"
                        status="danger"
                        icon={<IconTrash />}
                        onClick={() => handleDelete(key)}
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
                            <div>
                                <h2 className="text-xl font-semibold">API keys</h2>
                                <p className="text-muted">
                                    Add your API keys to run evaluations with your own account. Supports OpenAI,
                                    Anthropic, and Google Gemini.
                                </p>
                            </div>
                            <LemonButton type="primary" icon={<IconPlus />} onClick={() => setNewKeyModalOpen(true)}>
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
                                    Add your API key to run evaluations with your own account.
                                    <br />
                                    Supports OpenAI, Anthropic, and Google Gemini.
                                </p>
                                <LemonButton
                                    type="primary"
                                    icon={<IconPlus />}
                                    onClick={() => setNewKeyModalOpen(true)}
                                >
                                    Add API key
                                </LemonButton>
                            </div>
                        ) : (
                            <LemonTable
                                columns={columns}
                                dataSource={providerKeys}
                                loading={providerKeysLoading}
                                rowKey="id"
                            />
                        )}
                    </>
                )}
            </div>
            <AddKeyModal />
            {editingKey && <EditKeyModal keyToEdit={editingKey} />}
        </>
    )
}
