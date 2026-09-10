import { type ReactElement, useEffect } from 'react'

import { PostHogLogo } from './PostHogLogo'

export function AppErrorState({ message }: { message: string }): ReactElement {
    useEffect(() => {
        console.error('[PostHog MCP App] AppErrorState:', message)
    }, [message])

    return (
        <div className="flex flex-col items-center justify-center gap-3 h-[200px] px-4">
            <PostHogLogo size={40} />
            <span className="text-xs text-center text-destructive-foreground">{message}</span>
        </div>
    )
}
