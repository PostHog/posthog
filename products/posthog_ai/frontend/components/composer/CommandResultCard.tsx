import { IconX } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

export interface CommandResultCardProps {
    title: string
    /** Null while the answer loads. */
    body: string | null
    onDismiss: () => void
}

/** The output of an app slash command (`/btw`, `/usage`). It stays out of the conversation. */
export function CommandResultCard({ title, body, onDismiss }: CommandResultCardProps): JSX.Element {
    return (
        <div
            className="border border-primary rounded-lg bg-surface-primary px-3 py-2 mb-2 text-sm"
            data-attr="sandbox-composer-command-result"
        >
            <div className="flex items-start gap-2">
                <div className="font-semibold min-w-0 flex-1 break-words">{title}</div>
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    onClick={onDismiss}
                    tooltip="Dismiss"
                    data-attr="sandbox-composer-command-result-dismiss"
                />
            </div>
            {body === null ? (
                <div className="flex items-center gap-2 text-muted mt-1">
                    <Spinner />
                    <span>Thinking…</span>
                </div>
            ) : (
                <LemonMarkdown className="mt-1 max-h-60 overflow-y-auto">{body}</LemonMarkdown>
            )}
        </div>
    )
}
