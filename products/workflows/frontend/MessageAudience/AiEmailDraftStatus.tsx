import { IconInfo, IconSparkles } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

export type AiEmailDraftStatusProps =
    | { status: 'loading' }
    | { status: 'applied'; onReview?: () => void }
    | { status: 'failed'; message: string }

export function AiEmailDraftStatus(props: AiEmailDraftStatusProps): JSX.Element {
    if (props.status === 'loading') {
        return (
            <div className="flex items-center gap-2 text-sm text-secondary" data-attr="ai-email-draft-loading">
                <Spinner />
                <span>Writing a first draft with AI. If you edit the email before it's ready, your version stays.</span>
            </div>
        )
    }
    if (props.status === 'failed') {
        return (
            <div className="flex items-center gap-2 text-sm text-secondary" data-attr="ai-email-draft-failed">
                <IconInfo className="shrink-0" />
                <span>{props.message}</span>
            </div>
        )
    }
    return (
        <div
            className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-secondary"
            data-attr="ai-email-draft-applied"
        >
            <IconSparkles className="shrink-0" />
            <span>
                {props.onReview
                    ? 'AI wrote the first draft of this email. Check it before anyone gets it.'
                    : 'AI wrote this first draft. Check it before you send it.'}
            </span>
            {props.onReview ? (
                <LemonButton size="xsmall" type="secondary" onClick={props.onReview} data-attr="ai-email-draft-review">
                    Review email
                </LemonButton>
            ) : null}
        </div>
    )
}
