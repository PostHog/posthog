import { JSX } from 'react'

import { Spinner } from '@posthog/lemon-ui'

interface StatusNotificationViewProps {
    status: string
    isComplete?: boolean
}

export function StatusNotificationView({ status, isComplete }: StatusNotificationViewProps): JSX.Element | null {
    if (status === 'compacting') {
        if (isComplete) {
            return null
        }
        return (
            <div className="my-1 border-l-2 border-accent py-1 pl-3">
                <div className="flex items-center gap-2">
                    <Spinner className="text-[14px] text-accent" textColored />
                    <span className="text-[13px] text-muted">Compacting conversation history...</span>
                </div>
            </div>
        )
    }

    // Generic status display for other statuses
    return (
        <div className="my-1 border-l-2 border-border py-1 pl-3">
            <div className="flex items-center gap-2">
                <span className="text-[13px] text-muted">Status: {status}</span>
            </div>
        </div>
    )
}
