import { IconPlug, IconRefresh, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { NETWORK_LOAD_ERROR_MESSAGE } from '../../../lib/load-error'

export interface TaskLoadErrorStateProps {
    message: string
    onRetry: () => void
    retrying: boolean
}

export function TaskLoadErrorState({ message, onRetry, retrying }: TaskLoadErrorStateProps): JSX.Element {
    const isNetworkError = message === NETWORK_LOAD_ERROR_MESSAGE
    return (
        <div
            className="flex flex-1 flex-col items-center justify-center gap-3 px-4 py-16 text-center"
            data-attr="task-load-error"
        >
            {isNetworkError ? (
                <IconPlug className="text-3xl text-muted" />
            ) : (
                <IconWarning className="text-3xl text-warning" />
            )}
            <div className="flex max-w-100 flex-col gap-1">
                <h3 className="mb-0 text-base font-semibold">
                    {isNetworkError ? "Can't reach PostHog" : "Couldn't load this task"}
                </h3>
                <p className="mb-0 text-sm text-muted">
                    {isNetworkError ? 'Check your connection and try again.' : message}
                </p>
            </div>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconRefresh />}
                onClick={onRetry}
                loading={retrying}
                disabledReason={retrying ? 'Trying again' : undefined}
                data-attr="task-load-error-retry"
            >
                Try again
            </LemonButton>
        </div>
    )
}
