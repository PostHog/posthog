import { useActions, useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonCard, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SendFromCodeSurface, firstCodeSendLogic } from './firstCodeSendLogic'

export function FirstSendStatus({ surface }: { surface: SendFromCodeSurface }): JSX.Element | null {
    const logic = firstCodeSendLogic({ surface })
    const { firstCodeSend, pollingStopped } = useValues(logic)
    const { checkAgain } = useActions(logic)

    if (firstCodeSend.status === 'arrived') {
        return (
            <LemonCard
                hoverEffect={false}
                className="flex flex-wrap items-center gap-2 px-4 py-3 border-success bg-success-highlight"
                data-attr="send-from-code-first-send-arrived"
            >
                <IconCheckCircle className="text-success text-lg shrink-0" />
                <span className="flex-1 min-w-0">
                    <b>Your code sent its first email.</b> PostHog sent{' '}
                    <code className="break-all">{firstCodeSend.codeEmail.key}</code> and linked it to the person who got
                    it.
                </span>
                <LemonButton
                    type="secondary"
                    size="small"
                    to={urls.transactionalCodeEmail(firstCodeSend.codeEmail.id)}
                    data-attr="send-from-code-open-first-email"
                >
                    Open email
                </LemonButton>
            </LemonCard>
        )
    }

    if (firstCodeSend.status !== 'waiting') {
        return null
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-wrap items-center gap-2 px-4 py-3">
            {pollingStopped ? null : <Spinner textColored />}
            <span className="flex-1 min-w-0 text-secondary">
                {pollingStopped
                    ? 'No email from your code yet.'
                    : 'Waiting for your first send. This updates by itself when it arrives.'}
            </span>
            {pollingStopped ? (
                <LemonButton type="secondary" size="small" onClick={checkAgain} data-attr="send-from-code-check-again">
                    Check again
                </LemonButton>
            ) : null}
        </LemonCard>
    )
}
