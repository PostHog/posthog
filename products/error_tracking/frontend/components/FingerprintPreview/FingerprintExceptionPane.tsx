import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { ErrorEventType } from 'lib/components/Errors/types'

import { ExceptionCard } from '../ExceptionCard'
import { StyleVariables } from '../StyleVariables'

interface FingerprintExceptionPaneProps {
    issueId: string
    activeFingerprint: string | null
    event: ErrorEventType | null
    loading: boolean
    error: string | null
    onRetry: () => void
}

export function FingerprintExceptionPane({
    issueId,
    activeFingerprint,
    event,
    loading,
    error,
    onRetry,
}: FingerprintExceptionPaneProps): JSX.Element {
    if (!activeFingerprint) {
        return (
            <div className="flex min-h-0 items-center justify-center text-center text-muted">
                Select a fingerprint to see its exception.
            </div>
        )
    }

    if (loading) {
        return (
            <div className="flex min-h-0 items-center justify-center">
                <Spinner />
            </div>
        )
    }

    if (error) {
        return (
            <div className="flex min-h-0 flex-col items-center justify-center gap-2 text-center">
                <span className="text-muted">Couldn't load a sample exception for this fingerprint.</span>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    onClick={onRetry}
                    data-attr="error-tracking-manage-fingerprint-retry"
                >
                    Retry
                </LemonButton>
            </div>
        )
    }

    if (!event) {
        return (
            <div className="flex min-h-0 flex-col items-center justify-center gap-1 text-center">
                <span className="text-muted">No sample exception found for this fingerprint.</span>
                <span className="text-xs text-muted">Its events may have fallen out of the retention window.</span>
            </div>
        )
    }

    return (
        <div className="flex min-h-0 flex-col overflow-hidden">
            <StyleVariables className="flex min-h-0 flex-1 flex-col">
                <ExceptionCard issueId={issueId} issueName={null} loading={false} event={event} />
            </StyleVariables>
        </div>
    )
}
