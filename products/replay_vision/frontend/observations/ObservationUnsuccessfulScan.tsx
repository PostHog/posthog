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
    if ((!failed && observation.status !== 'ineligible') || !observation.error_reason) {
        return null
    }
    const failure = failed ? parseFailureReason(observation.error_reason) : null
    const ineligible = failed ? null : parseIneligibleReason(observation.error_reason)
    const description = failure
        ? failureKindDescription(failure.kind)
        : ineligible
          ? ineligibleKindDescription(ineligible.kind)
          : observation.error_reason
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
                    errorReason={observation.error_reason}
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
