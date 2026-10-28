import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { mcpCustomHarnessesLogic } from './mcpCustomHarnessesLogic'

export function McpCustomHarnessForm(): JSX.Element {
    const { isCustomHarnessFormSubmitting, saveInProgressReason, customHarnessForm, customHarnessFormValidationErrors } =
        useValues(mcpCustomHarnessesLogic)
    const iconPreview =
        customHarnessForm.icon && !customHarnessFormValidationErrors.icon ? customHarnessForm.icon : null
    const { cancelEditingHarness } = useActions(mcpCustomHarnessesLogic)

    return (
        <Form
            logic={mcpCustomHarnessesLogic}
            formKey="customHarnessForm"
            enableFormOnSubmit
            className="flex flex-col gap-2 border rounded p-2 bg-surface-primary"
        >
            <div className="flex flex-wrap items-start gap-2">
                <LemonField name="name" label="Name" className="flex-1 min-w-60">
                    <LemonInput autoFocus placeholder="Acme agent" maxLength={100} />
                </LemonField>
                <LemonField
                    name="match_pattern"
                    label="Client name contains"
                    help="Not case sensitive. Matches the client name or User-Agent product the harness reports."
                    className="flex-1 min-w-60"
                >
                    <LemonInput placeholder="acme-agent" maxLength={100} />
                </LemonField>
            </div>
            <div className="flex items-start gap-2">
                <LemonField
                    name="icon"
                    label="Icon (optional)"
                    help="Paste a PNG, JPEG, GIF or WebP image as a data URI. It can be 16 KB and 256 by 256 pixels at most."
                    className="flex-1 min-w-60"
                >
                    <LemonInput placeholder="data:image/png;base64,..." />
                </LemonField>
                {iconPreview && (
                    <img src={iconPreview} alt="Icon preview" className="size-8 mt-7 shrink-0 object-contain" />
                )}
            </div>
            <div className="flex justify-end gap-2">
                <LemonButton type="secondary" onClick={cancelEditingHarness} disabledReason={saveInProgressReason}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    loading={isCustomHarnessFormSubmitting}
                    data-attr="mcp-custom-harness-save"
                >
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}
