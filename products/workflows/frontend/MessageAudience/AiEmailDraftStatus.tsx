import { Spinner } from '@posthog/lemon-ui'

export function AiEmailDraftStatus(): JSX.Element {
    return (
        <div className="flex items-center gap-2 text-sm text-secondary" data-attr="ai-email-draft-loading">
            <Spinner />
            <span>Writing a first draft with AI. If you edit the email before it's ready, your version stays.</span>
        </div>
    )
}
