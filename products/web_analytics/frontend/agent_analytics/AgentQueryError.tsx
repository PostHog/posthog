import { ReactNode } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

interface AgentQueryErrorProps {
    error: string | null
    subject: string
    onRetry: () => void
    loading: boolean
    children: ReactNode
}

export const AgentQueryError = ({ error, subject, onRetry, loading, children }: AgentQueryErrorProps): JSX.Element => {
    if (error) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: onRetry, loading }}>
                {`Could not load ${subject}. Try again. If it keeps happening, contact support.`}
            </LemonBanner>
        )
    }
    return <>{children}</>
}
