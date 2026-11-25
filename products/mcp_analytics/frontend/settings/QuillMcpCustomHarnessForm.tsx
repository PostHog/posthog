import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { Button, Card, CardContent } from '@posthog/quill'

import { HarnessIconMask } from '../components/HarnessIconMask'
import { mcpCustomHarnessesLogic } from './mcpCustomHarnessesLogic'
import { PREVIEW_BACKGROUNDS } from './McpCustomHarnessForm'
import { QuillHarnessFormField } from './QuillHarnessFormField'

export function QuillMcpCustomHarnessForm({ iconPreview }: { iconPreview: string | null }): JSX.Element {
    const { isCustomHarnessFormSubmitting, saveInProgressReason } = useValues(mcpCustomHarnessesLogic)
    const { cancelEditingHarness } = useActions(mcpCustomHarnessesLogic)

    return (
        <Card size="sm">
            <CardContent>
                <Form
                    logic={mcpCustomHarnessesLogic}
                    formKey="customHarnessForm"
                    enableFormOnSubmit
                    className="flex flex-col gap-3"
                >
                    <div className="flex flex-wrap items-start gap-2">
                        <QuillHarnessFormField
                            name="name"
                            label="Name"
                            placeholder="Acme agent"
                            maxLength={100}
                            autoFocus
                            className="flex-1 min-w-60"
                        />
                        <QuillHarnessFormField
                            name="match_pattern"
                            label="Client name contains"
                            description="Not case sensitive. Matches the client name or User-Agent product the harness reports."
                            placeholder="acme-agent"
                            maxLength={100}
                            className="flex-1 min-w-60"
                        />
                    </div>
                    <div className="flex flex-wrap items-start gap-2">
                        <QuillHarnessFormField
                            name="icon"
                            label="Icon (optional)"
                            description="Paste a PNG, GIF or WebP image with a transparent background as a data URI. It can be 16 KB and 256 by 256 pixels at most. It shows in one color, like the other harness logos."
                            placeholder="data:image/png;base64,..."
                            className="flex-1 min-w-60"
                        />
                        {iconPreview && (
                            <div className="flex gap-1 mt-6 shrink-0">
                                {PREVIEW_BACKGROUNDS.map(({ name, className }) => (
                                    <div key={name} className={`flex rounded border p-2 ${className}`}>
                                        <HarnessIconMask
                                            src={iconPreview}
                                            label={`Icon preview on a ${name} background`}
                                        />
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                    <div className="flex flex-wrap justify-end gap-2">
                        <Button variant="outline" onClick={cancelEditingHarness} disabledReason={saveInProgressReason}>
                            Cancel
                        </Button>
                        <Button
                            variant="primary"
                            type="submit"
                            loading={isCustomHarnessFormSubmitting}
                            data-attr="mcp-custom-harness-save"
                        >
                            Save
                        </Button>
                    </div>
                </Form>
            </CardContent>
        </Card>
    )
}
