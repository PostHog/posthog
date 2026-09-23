import { ObservationResultSummary } from '../../components/ObservationCard'
import type { ReplayObservationApi } from '../../generated/api.schemas'
import { unsuccessfulScanReason } from '../types'

export function ObservationRowResult({ observation }: { observation: ReplayObservationApi }): JSX.Element {
    if (observation.status === 'failed' || observation.status === 'ineligible') {
        const reason = unsuccessfulScanReason(observation.status, observation.error_reason)
        return reason ? (
            <span className="text-sm text-secondary line-clamp-2">{reason}</span>
        ) : (
            <ObservationResultSummary observation={observation} />
        )
    }
    return <ObservationResultSummary observation={observation} />
}
