import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Textarea,
} from '@posthog/quill'

import type { McpInstallationScope } from '../mcpStoreLogic'
import { mcpStoreLogic } from '../mcpStoreLogic'
import { OAuthRedirectUri } from '../OAuthRedirectUri'
import { QuillMcpFormField } from './QuillMcpFormField'

const FORM_ID = 'mcp-add-custom-server-form'

export function QuillAddCustomServerForm({
    title,
    subtitle,
    sharedRestrictionReason,
    authTypeOptions,
    scopeOptions,
}: {
    title: string
    subtitle: string
    sharedRestrictionReason: string | null
    authTypeOptions: { value: string; label: string }[]
    scopeOptions: { value: McpInstallationScope; label: string }[]
}): JSX.Element {
    const { addCustomServerModalVisible, customServerForm, isCustomServerFormSubmitting, customServerFormPrefilled } =
        useValues(mcpStoreLogic)
    const { setCustomServerFormValue, closeAddCustomServerModal } = useActions(mcpStoreLogic)
    const canAddShared = !sharedRestrictionReason

    return (
        <Dialog
            open={addCustomServerModalVisible}
            onOpenChange={(open: boolean) => {
                if (!open) {
                    closeAddCustomServerModal()
                }
            }}
        >
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                    <DialogDescription>{subtitle}</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <Form
                        logic={mcpStoreLogic}
                        formKey="customServerForm"
                        id={FORM_ID}
                        enableFormOnSubmit
                        className="flex flex-col gap-4"
                    >
                        <QuillMcpFormField
                            name="scope"
                            label="Visibility"
                            description={
                                canAddShared
                                    ? 'Shared servers are available to all project members and autonomous agents.'
                                    : 'Only project admins can add shared servers.'
                            }
                        >
                            {({ id, value }) => (
                                <Select
                                    value={value}
                                    onValueChange={(next) =>
                                        setCustomServerFormValue('scope', next as McpInstallationScope)
                                    }
                                >
                                    <SelectTrigger id={id} className="w-full" disabledReason={sharedRestrictionReason}>
                                        <SelectValue>
                                            {(selected: string) =>
                                                scopeOptions.find((option) => option.value === selected)?.label
                                            }
                                        </SelectValue>
                                    </SelectTrigger>
                                    <SelectContent>
                                        {(canAddShared ? scopeOptions : [scopeOptions[0]]).map((option) => (
                                            <SelectItem key={option.value} value={option.value}>
                                                {option.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            )}
                        </QuillMcpFormField>
                        {!customServerFormPrefilled && (
                            <>
                                <QuillMcpFormField name="name" label="Name">
                                    {({ id, value, onChange }) => (
                                        <Input
                                            id={id}
                                            value={value ?? ''}
                                            onChange={(event) => onChange(event.target.value)}
                                            placeholder="My MCP server"
                                            autoFocus
                                        />
                                    )}
                                </QuillMcpFormField>
                                <QuillMcpFormField name="url" label="Server URL">
                                    {({ id, value, onChange }) => (
                                        <Input
                                            id={id}
                                            value={value ?? ''}
                                            onChange={(event) => onChange(event.target.value)}
                                            placeholder="https://mcp.example.com"
                                            className="font-mono"
                                        />
                                    )}
                                </QuillMcpFormField>
                                <QuillMcpFormField name="description" label="Description">
                                    {({ id, value, onChange }) => (
                                        <Textarea
                                            id={id}
                                            value={value ?? ''}
                                            onChange={(event) => onChange(event.target.value)}
                                            placeholder="What does this server do?"
                                        />
                                    )}
                                </QuillMcpFormField>
                                <QuillMcpFormField name="auth_type" label="Authentication">
                                    {({ id, value }) => (
                                        <Select
                                            value={value}
                                            onValueChange={(next) => setCustomServerFormValue('auth_type', next)}
                                        >
                                            <SelectTrigger id={id} className="w-full">
                                                <SelectValue>
                                                    {(selected: string) =>
                                                        authTypeOptions.find((option) => option.value === selected)
                                                            ?.label
                                                    }
                                                </SelectValue>
                                            </SelectTrigger>
                                            <SelectContent>
                                                {authTypeOptions.map((option) => (
                                                    <SelectItem key={option.value} value={option.value}>
                                                        {option.label}
                                                    </SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    )}
                                </QuillMcpFormField>
                            </>
                        )}
                        {customServerForm.auth_type === 'api_key' && (
                            <QuillMcpFormField name="api_key" label="API key">
                                {({ id, value, onChange }) => (
                                    <Input
                                        id={id}
                                        type="password"
                                        value={value ?? ''}
                                        onChange={(event) => onChange(event.target.value)}
                                        placeholder="Enter API key"
                                    />
                                )}
                            </QuillMcpFormField>
                        )}
                        {customServerForm.auth_type === 'oauth' && !customServerFormPrefilled && (
                            <Collapsible>
                                <CollapsibleTrigger className="w-full">
                                    Advanced — bring your own OAuth client
                                </CollapsibleTrigger>
                                <CollapsibleContent>
                                    <div className="flex flex-col gap-4 pt-2">
                                        <OAuthRedirectUri />
                                        <QuillMcpFormField
                                            name="client_id"
                                            label="OAuth client ID"
                                            description="Leave blank to let PostHog register a client for you via Dynamic Client Registration."
                                        >
                                            {({ id, value, onChange }) => (
                                                <Input
                                                    id={id}
                                                    value={value ?? ''}
                                                    onChange={(event) => onChange(event.target.value)}
                                                    placeholder="Optional"
                                                />
                                            )}
                                        </QuillMcpFormField>
                                        <QuillMcpFormField
                                            name="client_secret"
                                            label="OAuth client secret"
                                            description="Only needed for confidential clients. Ignored unless a client ID is set."
                                        >
                                            {({ id, value, onChange }) => (
                                                <Input
                                                    id={id}
                                                    type="password"
                                                    value={value ?? ''}
                                                    onChange={(event) => onChange(event.target.value)}
                                                    placeholder="Optional"
                                                />
                                            )}
                                        </QuillMcpFormField>
                                    </div>
                                </CollapsibleContent>
                            </Collapsible>
                        )}
                    </Form>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeAddCustomServerModal}>
                        Cancel
                    </Button>
                    <Button variant="primary" type="submit" form={FORM_ID} loading={isCustomServerFormSubmitting}>
                        {customServerFormPrefilled ? 'Connect' : 'Add server'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
