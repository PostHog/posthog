import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonCollapse, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { mcpStoreLogic } from '../mcpStoreLogic'

const AUTH_TYPE_OPTIONS = [
    { value: 'api_key', label: 'API key' },
    { value: 'oauth', label: 'OAuth' },
]

export function AddCustomServerForm(): JSX.Element {
    const { addCustomServerModalVisible, customServerForm, isCustomServerFormSubmitting, customServerFormPrefilled } =
        useValues(mcpStoreLogic)
    const { setCustomServerFormValue, closeAddCustomServerModal } = useActions(mcpStoreLogic)

    const title = customServerFormPrefilled ? `Connect ${customServerForm.name}` : 'Add MCP server'
    const subtitle = customServerFormPrefilled
        ? 'This server is pre-configured by PostHog. Just paste your credentials below.'
        : 'Connect any MCP server. PostHog will register a client via Dynamic Client Registration when needed.'

    return (
        <LemonModal
            isOpen={addCustomServerModalVisible}
            onClose={closeAddCustomServerModal}
            overlayClassName="!items-center"
            title={title}
            description={subtitle}
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton type="secondary" onClick={closeAddCustomServerModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        form="mcp-add-custom-server-form"
                        loading={isCustomServerFormSubmitting}
                    >
                        {customServerFormPrefilled ? 'Connect' : 'Add server'}
                    </LemonButton>
                </div>
            }
            width={560}
        >
            <Form
                logic={mcpStoreLogic}
                formKey="customServerForm"
                id="mcp-add-custom-server-form"
                enableFormOnSubmit
                className="deprecated-space-y-3"
            >
                {!customServerFormPrefilled && (
                    <>
                        <LemonField name="name" label="Name">
                            <LemonInput placeholder="My MCP server" fullWidth autoFocus />
                        </LemonField>
                        <LemonField name="url" label="Server URL">
                            <LemonInput placeholder="https://mcp.example.com" className="font-mono" fullWidth />
                        </LemonField>
                        <LemonField name="description" label="Description">
                            <LemonTextArea placeholder="What does this server do?" />
                        </LemonField>
                        <LemonField name="auth_type" label="Authentication">
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
                {customServerForm.auth_type === 'oauth' && !customServerFormPrefilled && (
                    <LemonCollapse
                        panels={[
                            {
                                key: 'advanced',
                                header: 'Advanced — bring your own OAuth client',
                                content: (
                                    <div className="deprecated-space-y-3">
                                        <LemonField
                                            name="client_id"
                                            label="OAuth client ID"
                                            help="Leave blank to let PostHog register a client for you via Dynamic Client Registration."
                                        >
                                            <LemonInput placeholder="Optional" fullWidth />
                                        </LemonField>
                                        <LemonField
                                            name="client_secret"
                                            label="OAuth client secret"
                                            help="Only needed for confidential clients. Ignored unless a client ID is set."
                                        >
                                            <LemonInput placeholder="Optional" type="password" fullWidth />
                                        </LemonField>
                                    </div>
                                ),
                            },
                        ]}
                    />
                )}
            </Form>
        </LemonModal>
    )
}
