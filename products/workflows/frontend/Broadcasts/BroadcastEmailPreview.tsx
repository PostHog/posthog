import { useActions, useValues } from 'kea'

import { IconSend } from '@posthog/icons'
import { LemonButton, LemonSearchableSelect, Spinner } from '@posthog/lemon-ui'

import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { broadcastTestSendLogic } from './broadcastTestSendLogic'
import { broadcastWizardLogic } from './broadcastWizardLogic'
import { SendTestBroadcastModal } from './SendTestBroadcastModal'

function PreviewRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="w-16 shrink-0 text-xs font-semibold uppercase tracking-wide text-muted">{label}</span>
            <div className="min-w-0 flex-1">{children}</div>
        </div>
    )
}

/**
 * Shows the email as one person in the audience will receive it, with their own property values
 * filled in. Anything the person has no value for stays on screen as `{{ ... }}` rather than
 * rendering blank, so a missing variable is visible before the send rather than after.
 */
export function BroadcastEmailPreview(): JSX.Element {
    const { email } = useValues(broadcastWizardLogic)
    const { persons, personsLoading, previewPerson, previewSubject, previewHtml, previewTo } =
        useValues(broadcastPreviewLogic)
    const { selectPerson } = useActions(broadcastPreviewLogic)
    const { setModalOpen } = useActions(broadcastTestSendLogic)

    const hasContent = !!(email.html || email.text)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-muted text-xs">Preview and test before this reaches the audience.</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconSend />}
                    onClick={() => setModalOpen(true)}
                    data-attr="broadcast-open-test-email"
                >
                    Send test email
                </LemonButton>
            </div>
            <SendTestBroadcastModal />

            <div className="flex flex-col gap-2 rounded border border-border bg-surface-secondary p-3">
                <PreviewRow label="To">
                    {personsLoading ? (
                        <Spinner />
                    ) : persons.length > 0 ? (
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonSearchableSelect
                                value={previewPerson?.id}
                                options={persons.map((person) => ({
                                    value: person.id,
                                    label: person.displayName,
                                }))}
                                onChange={(value) => selectPerson(value ?? null)}
                                searchPlaceholder="Find a person..."
                                size="small"
                                data-attr="broadcast-preview-person"
                            />
                            {previewTo && previewTo !== previewPerson?.displayName && (
                                <span className="text-muted text-xs">{previewTo}</span>
                            )}
                        </div>
                    ) : (
                        <span className="text-muted">
                            No one matches this audience yet, so variables stay unfilled below.
                        </span>
                    )}
                </PreviewRow>

                <PreviewRow label="Subject">
                    {previewSubject || <span className="text-muted">No subject</span>}
                </PreviewRow>
            </div>

            {hasContent ? (
                email.html ? (
                    <iframe
                        srcDoc={previewHtml}
                        sandbox=""
                        title="Email preview"
                        className="h-96 w-full rounded border border-border bg-white"
                    />
                ) : (
                    <div className="text-muted max-h-96 overflow-y-auto whitespace-pre-wrap text-sm">{email.text}</div>
                )
            ) : (
                <span className="text-muted">No content yet</span>
            )}

            {previewPerson && (
                <span className="text-xs text-muted">
                    Values come from {previewPerson.displayName}. Anything still shown as a variable is not set for
                    them, and sends as blank text.
                </span>
            )}
        </div>
    )
}
