import { ReactNode } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

interface AgentQueryErrorProps {
    error: string | null
    message: string
    onRetry: () => void
    loading: boolean
    children: ReactNode
}

export const AgentQueryError = ({ error, message, onRetry, loading, children }: AgentQueryErrorProps): JSX.Element => {
    if (error) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: onRetry, loading }}>
                {message}
            </LemonBanner>
        )
    }
    return <>{children}</>
}
