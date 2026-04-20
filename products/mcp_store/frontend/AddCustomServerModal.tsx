import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { mcpStoreLogic } from './mcpStoreLogic'

const AUTH_TYPE_OPTIONS = [
    { value: 'api_key', label: 'API key' },
    { value: 'oauth', label: 'OAuth' },
]

export function AddCustomServerModal(): JSX.Element {
    const { addCustomServerModalVisible, customServerForm, isCustomServerFormSubmitting, customServerFormPrefilled } =
        useValues(mcpStoreLogic)
    const { closeAddCustomServerModal, setCustomServerFormValue } = useActions(mcpStoreLogic)

    const title = customServerFormPrefilled ? `Connect ${customServerForm.name}` : 'Add custom MCP server'

    return (
        <LemonModal title={title} isOpen={addCustomServerModalVisible} onClose={closeAddCustomServerModal} simple>
            <Form logic={mcpStoreLogic} formKey="customServerForm" enableFormOnSubmit className="LemonModal__layout">
                <LemonModal.Header>
                    <h3>{title}</h3>
                </LemonModal.Header>
                <LemonModal.Content>
                    <div className="flex flex-col gap-3">
                        {!customServerFormPrefilled && (
                            <>
                                <LemonField name="name" label="Name">
                                    <LemonInput placeholder="My MCP server" fullWidth />
                                </LemonField>
                                <LemonField name="url" label="URL">
                                    <LemonInput placeholder="https://mcp.example.com" fullWidth />
                                </LemonField>
                                <LemonField name="description" label="Description">
                                    <LemonTextArea placeholder="What does this server do?" />
                                </LemonField>
                                <LemonField name="auth_type" label="Auth type">
                                    <LemonSelect
                                        onChange={(val) => setCustomServerFormValue('auth_type', val)}
                                        options={AUTH_TYPE_OPTIONS}
                                        fullWidth
                                    />
                                </LemonField>
                            </>
                        )}
                        {customServerForm.auth_type === 'api_key' && (
                            <LemonField name="api_key" label="API key">
                                <LemonInput placeholder="Enter API key" type="password" fullWidth />
                            </LemonField>
                        )}
                    </div>
                </LemonModal.Content>
                <LemonModal.Footer>
                    <LemonButton type="secondary" onClick={closeAddCustomServerModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" htmlType="submit" loading={isCustomServerFormSubmitting}>
                        {customServerFormPrefilled ? 'Connect' : 'Add server'}
                    </LemonButton>
                </LemonModal.Footer>
            </Form>
        </LemonModal>
    )
}
