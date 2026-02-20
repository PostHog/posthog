import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'
import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import { mcpStoreLogic } from './mcpStoreLogic'

const AUTH_TYPE_OPTIONS = [
    { value: 'none', label: 'None' },
    { value: 'api_key', label: 'API key' },
    { value: 'oauth', label: 'OAuth' },
]

export function AddCustomServerModal(): JSX.Element {
    const { addCustomServerModalVisible } = useValues(mcpStoreLogic)
    const { closeAddCustomServerModal, loadInstallations } = useActions(mcpStoreLogic)

    const [name, setName] = useState('')
    const [url, setUrl] = useState('')
    const [description, setDescription] = useState('')
    const [authType, setAuthType] = useState('none')
    const [apiKey, setApiKey] = useState('')
    const [saving, setSaving] = useState(false)

    const handleSubmit = async (): Promise<void> => {
        setSaving(true)
        try {
            const result = await api.mcpServerInstallations.installCustom({
                name,
                url,
                auth_type: authType,
                api_key: apiKey,
                description,
            })

            if (result?.redirect_url) {
                window.location.href = result.redirect_url
                return
            }

            lemonToast.success('Server added and installed')
            loadInstallations()
            closeAddCustomServerModal()
            setName('')
            setUrl('')
            setDescription('')
            setAuthType('none')
            setApiKey('')
        } catch (e: any) {
            if (e.status === 302 || e.detail?.includes?.('redirect')) {
                return
            }
            lemonToast.error(e.detail || 'Failed to add server')
        } finally {
            setSaving(false)
        }
    }

    return (
        <LemonModal
            title="Add custom MCP server"
            isOpen={addCustomServerModalVisible}
            onClose={closeAddCustomServerModal}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeAddCustomServerModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={saving}
                        disabledReason={!name || !url ? 'Name and URL are required' : undefined}
                    >
                        Add server
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                <div>
                    <label className="font-semibold">Name</label>
                    <LemonInput value={name} onChange={setName} placeholder="My MCP server" fullWidth />
                </div>
                <div>
                    <label className="font-semibold">URL</label>
                    <LemonInput value={url} onChange={setUrl} placeholder="https://mcp.example.com" fullWidth />
                </div>
                <div>
                    <label className="font-semibold">Description</label>
                    <LemonTextArea
                        value={description}
                        onChange={setDescription}
                        placeholder="What does this server do?"
                    />
                </div>
                <div>
                    <label className="font-semibold">Auth type</label>
                    <LemonSelect
                        value={authType}
                        onChange={(val) => {
                            setAuthType(val)
                            if (val !== 'api_key') {
                                setApiKey('')
                            }
                        }}
                        options={AUTH_TYPE_OPTIONS}
                        fullWidth
                    />
                </div>
                {authType === 'api_key' && (
                    <div>
                        <label className="font-semibold">API key</label>
                        <LemonInput
                            value={apiKey}
                            onChange={setApiKey}
                            placeholder="Enter API key"
                            type="password"
                            fullWidth
                        />
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
