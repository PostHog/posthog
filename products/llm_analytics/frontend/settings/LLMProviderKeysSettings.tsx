import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonModal,
    LemonSkeleton,
    LemonSwitch,
    LemonTable,
    LemonTag,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { IconKey } from 'lib/lemon-ui/icons'

import { TrialUsageMeterDisplay } from './TrialUsageMeter'
import { KeyValidationResult, LLMProviderKey, LLMProviderKeyState, llmProviderKeysLogic } from './llmProviderKeysLogic'

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

function KeyValidationStatus({
    result,
    isValidating,
}: {
    result: KeyValidationResult | null
    isValidating: boolean
}): JSX.Element | null {
    if (isValidating) {
        return <p className="text-xs text-muted mt-1">Validating key...</p>
    }

    if (!result) {
        return (
            <ul className="text-xs text-muted mt-1 list-disc pl-4 space-y-0.5">
                <li>Your key will be encrypted and stored securely</li>
                <li>Evaluations use GPT-5-mini, you pay OpenAI directly</li>
                <li>Each evaluation counts as an LLM analytics event</li>
            </ul>
        )
    }

    if (result.state === 'ok') {
        return <p className="text-xs text-success mt-1">Key validated successfully</p>
    }

    return <p className="text-xs text-danger mt-1">{result.error_message || 'Key validation failed'}</p>
}

function AddKeyModal(): JSX.Element {
    const { newKeyModalOpen, providerKeysLoading, preValidationResult, preValidationResultLoading } =
        useValues(llmProviderKeysLogic)
    const { setNewKeyModalOpen, createProviderKey, preValidateKey, clearPreValidation } =
        useActions(llmProviderKeysLogic)

    const [name, setName] = useState('')
    const [apiKey, setApiKey] = useState('')
    const [setAsActive, setSetAsActive] = useState(true)
    const [pendingSubmit, setPendingSubmit] = useState(false)

    const formatValid = apiKey.length > 0 && (apiKey.startsWith('sk-') || apiKey.startsWith('sk-proj-'))
    const keyValidated = preValidationResult?.state === 'ok'
    const isValid = name.length > 0 && formatValid

    // Reset form when modal closes
    useEffect(() => {
        if (!newKeyModalOpen) {
            setName('')
            setApiKey('')
            setSetAsActive(true)
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
                        provider: 'openai',
                        name,
                        api_key: apiKey,
                        set_as_active: setAsActive,
                    },
                })
            }
        }
    }, [pendingSubmit, preValidationResult, preValidationResultLoading, setAsActive, createProviderKey, name, apiKey])

    const handleClose = (): void => {
        setNewKeyModalOpen(false)
        clearPreValidation()
    }

    const handleSubmit = (): void => {
        if (keyValidated) {
            createProviderKey({
                payload: {
                    provider: 'openai',
                    name,
                    api_key: apiKey,
                    set_as_active: setAsActive,
                },
            })
        } else if (formatValid) {
            setPendingSubmit(true)
            preValidateKey({ apiKey })
        }
    }

    const handleApiKeyBlur = (): void => {
        if (formatValid && !preValidationResult) {
            preValidateKey({ apiKey })
        }
    }

    const handleApiKeyChange = (value: string): void => {
        setApiKey(value)
        if (preValidationResult) {
            clearPreValidation()
        }
    }

    return (
        <LemonModal
            isOpen={newKeyModalOpen}
            onClose={handleClose}
            title="Add OpenAI API key"
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
                    <div className="mt-1">
                        <LemonTag type="default">OpenAI</LemonTag>
                    </div>
                    <p className="text-xs text-muted mt-1">More providers coming soon</p>
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
                        placeholder="sk-..."
                        type="password"
                        autoComplete="off"
                        className="mt-1"
                        fullWidth
                        status={preValidationResult && preValidationResult.state !== 'ok' ? 'danger' : undefined}
                    />
                    <KeyValidationStatus result={preValidationResult} isValidating={preValidationResultLoading} />
                </div>
                <div className="flex items-center justify-between">
                    <div>
                        <label className="text-sm font-medium">Set as active</label>
                        <p className="text-xs text-muted">Use this key for running evaluations</p>
                    </div>
                    <LemonSwitch checked={setAsActive} onChange={setSetAsActive} />
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
        if (apiKey.length > 0 && (apiKey.startsWith('sk-') || apiKey.startsWith('sk-proj-'))) {
            preValidateKey({ apiKey })
        }
    }

    const handleApiKeyChange = (value: string): void => {
        setApiKey(value)
        if (preValidationResult) {
            clearPreValidation()
        }
    }

    const formatValid = apiKey.length === 0 || apiKey.startsWith('sk-') || apiKey.startsWith('sk-proj-')
    const keyValidated = apiKey.length === 0 || preValidationResult?.state === 'ok'
    const isValid = name.length > 0 && formatValid && keyValidated

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
                        <KeyValidationStatus result={preValidationResult} isValidating={preValidationResultLoading} />
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
        activeKey,
        editingKey,
        validatingKeyId,
    } = useValues(llmProviderKeysLogic)
    const { setNewKeyModalOpen, deleteProviderKey, setActiveKey, validateProviderKey, setEditingKey } =
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
            render: (_, key) => (
                <LemonTag type="default">{key.provider === 'openai' ? 'OpenAI' : key.provider}</LemonTag>
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
            title: 'Active',
            key: 'active',
            render: (_, key) => {
                const isActive = activeKey?.id === key.id
                const canActivate = key.state === 'ok'
                return (
                    <Tooltip
                        title={
                            isActive
                                ? 'Select another key to change the active key'
                                : !canActivate
                                  ? 'Validate the key before activating'
                                  : undefined
                        }
                    >
                        <span className="inline-flex">
                            <LemonSwitch
                                checked={isActive}
                                onChange={() => setActiveKey({ keyId: key.id })}
                                disabled={isActive || !canActivate}
                            />
                        </span>
                    </Tooltip>
                )
            },
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
                                    Evaluations use GPT-5-mini as the judge model. Add your OpenAI API key to run
                                    evaluations with your own account.
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
                                <p className="text-muted mb-4">
                                    Add your own OpenAI API key to run evaluations using your own account.
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
