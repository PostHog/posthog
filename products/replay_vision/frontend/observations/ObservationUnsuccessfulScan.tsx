import { LabeledRow } from '../components/LabeledRow'
import { ObservationRetryButton } from '../components/ObservationRetryButton'
import type { ReplayObservationApi } from '../generated/api.schemas'
import {
    failureKindDescription,
    ineligibleKindDescription,
    parseFailureReason,
    parseIneligibleReason,
} from '../replay_scanners/types'

export function ObservationUnsuccessfulScan({
    observation,
    retrying,
    onRetry,
}: {
    observation: ReplayObservationApi
    retrying: boolean
    onRetry: () => void
}): JSX.Element | null {
    const failed = observation.status === 'failed'
    if (!failed && observation.status !== 'ineligible') {
        return null
    }
    const errorReason = observation.error_reason
    const failure = failed && errorReason ? parseFailureReason(errorReason) : null
    const ineligible = !failed && errorReason ? parseIneligibleReason(errorReason) : null
    const description = failure
        ? failureKindDescription(failure.kind)
        : ineligible
          ? ineligibleKindDescription(ineligible.kind)
          : errorReason || 'No reason was recorded for this scan.'
    const message = (failure ?? ineligible)?.message

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <span className={`text-2xl font-bold ${failed ? 'text-danger' : 'text-muted'}`}>
                    {failed ? 'Scan failed' : 'Not scanned'}
                </span>
                <p className="text-sm text-default m-0 leading-snug">{description}</p>
            </div>
            {message && (
                <LabeledRow label={failed ? 'Error' : 'More info'}>
                    <p className={`text-sm text-default m-0 leading-snug ${failed ? 'font-mono' : ''}`}>{message}</p>
                </LabeledRow>
            )}
            <div>
                <ObservationRetryButton
                    status={observation.status}
                    errorReason={errorReason}
                    onRetry={onRetry}
                    loading={retrying}
                    emphasis={failed ? 'primary' : undefined}
                    size="small"
                    dataAttr="vision-observation-detail-retry"
                />
            </div>
        </div>
    )
}
