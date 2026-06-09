import { JSX } from 'react'

import { IconWarning } from '../primitives/icons'

interface ErrorNotificationViewProps {
    errorType: string
    message: string
}

export function ErrorNotificationView({ errorType, message }: ErrorNotificationViewProps): JSX.Element {
    // Context-related errors get a softer warning treatment with a recovery tip.
    const isContextError = errorType === 'invalid_request'

    const containerClass = isContextError
        ? 'bg-warning-highlight text-warning'
        : 'bg-danger-highlight text-danger'

    return (
        <div className="my-2">
            <div className={`flex items-start gap-2 rounded-lg p-3 text-[13px] ${containerClass}`}>
                <IconWarning className="mt-0.5 shrink-0" style={{ fontSize: 16 }} />
                <div className="flex flex-col gap-1">
                    <span className="text-sm font-medium text-default">{message}</span>
                    {isContextError && (
                        <span className="text-[13px] text-muted">
                            Tip: Type <code>/compact</code> to manually compress the conversation history.
                        </span>
                    )}
                </div>
            </div>
        </div>
    )
}
