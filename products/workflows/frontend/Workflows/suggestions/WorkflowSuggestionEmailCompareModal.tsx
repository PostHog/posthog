import { useState } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { emailPreviewDocument } from './suggestionEmailPreview'

function RenderedEmail({
    label,
    html,
    loadRemote,
}: {
    label: string
    html: string | null
    loadRemote: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1 flex-1 min-w-xl">
            <span className="text-xs font-semibold uppercase text-secondary">{label}</span>
            {html ? (
                // sandbox="" keeps scripts and same-origin access out of model-written HTML.
                <iframe
                    title={`Rendered email: ${label}`}
                    sandbox=""
                    referrerPolicy="no-referrer"
                    srcDoc={emailPreviewDocument(html, { loadRemote })}
                    className="w-full h-[70vh] bg-white rounded border"
                />
            ) : (
                <div className="flex items-center justify-center h-[70vh] rounded border text-secondary">
                    No email content
                </div>
            )}
        </div>
    )
}

export function WorkflowSuggestionEmailCompareModal({
    isOpen,
    onClose,
    isNewEmail,
    before,
    after,
}: {
    isOpen: boolean
    onClose: () => void
    isNewEmail: boolean
    before: string | null
    after: string | null
}): JSX.Element {
    // The suggested HTML is model-written, so its remote images load only when a person asks for them.
    const [loadRemote, setLoadRemote] = useState(false)
    const close = (): void => {
        setLoadRemote(false)
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={close}
            width={1400}
            title="Compare emails"
            description={
                isNewEmail
                    ? 'This suggestion adds a new email.'
                    : 'The email as it sends now, next to the email with this suggestion applied.'
            }
        >
            <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
                <span className="text-secondary">
                    {loadRemote
                        ? 'Remote images are loaded.'
                        : 'Remote images are blocked, so opening this preview does not contact the servers they come from.'}
                </span>
                <LemonButton
                    type="secondary"
                    size="small"
                    data-attr="workflow-suggestion-load-remote-images"
                    onClick={() => setLoadRemote(!loadRemote)}
                >
                    {loadRemote ? 'Block remote images' : 'Load remote images'}
                </LemonButton>
            </div>
            <div className="flex flex-wrap gap-4">
                {isNewEmail ? (
                    <RenderedEmail label="New email" html={after} loadRemote={loadRemote} />
                ) : (
                    <>
                        <RenderedEmail label="Now" html={before} loadRemote={loadRemote} />
                        <RenderedEmail label="Suggested" html={after} loadRemote={loadRemote} />
                    </>
                )}
            </div>
        </LemonModal>
    )
}
