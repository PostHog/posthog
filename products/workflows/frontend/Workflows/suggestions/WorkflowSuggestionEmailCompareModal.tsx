import { LemonModal } from '@posthog/lemon-ui'

function RenderedEmail({ label, html }: { label: string; html: string | null }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 flex-1 min-w-xl">
            <span className="text-xs font-semibold uppercase text-secondary">{label}</span>
            {html ? (
                // sandbox="" keeps scripts and same-origin access out of model-written HTML.
                <iframe
                    title={`Rendered email: ${label}`}
                    sandbox=""
                    srcDoc={html}
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
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1400}
            title="Compare emails"
            description={
                isNewEmail
                    ? 'This suggestion adds a new email.'
                    : 'The email as it sends now, next to the email with this suggestion applied.'
            }
        >
            <div className="flex flex-wrap gap-4">
                {isNewEmail ? (
                    <RenderedEmail label="New email" html={after} />
                ) : (
                    <>
                        <RenderedEmail label="Now" html={before} />
                        <RenderedEmail label="Suggested" html={after} />
                    </>
                )}
            </div>
        </LemonModal>
    )
}
