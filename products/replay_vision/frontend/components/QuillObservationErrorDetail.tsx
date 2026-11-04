import type { ReplayObservationApi } from '../generated/api.schemas'
import {
    failureKindDescription,
    ineligibleKindDescription,
    parseFailureReason,
    parseIneligibleReason,
} from '../replay_scanners/types'
import { QuillLabeledRow } from './QuillLabeledRow'

/** Why a failed or ineligible observation stopped, as a reason line and the raw detail under it. */
export function QuillObservationErrorDetail({
    status,
    errorReason,
}: {
    status: Extract<ReplayObservationApi['status'], 'failed' | 'ineligible'>
    errorReason: string
}): JSX.Element {
    const failed = status === 'failed'
    const failure = failed ? parseFailureReason(errorReason) : null
    const ineligible = failed ? null : parseIneligibleReason(errorReason)
    const reason = failure
        ? failureKindDescription(failure.kind)
        : ineligible
          ? ineligibleKindDescription(ineligible.kind)
          : errorReason
    const message = failure?.message ?? ineligible?.message
    return (
        <div className="flex flex-col gap-2">
            <QuillLabeledRow label="Reason">
                <p className="text-sm m-0 leading-snug">{reason}</p>
            </QuillLabeledRow>
            {message && (
                <QuillLabeledRow label="Details">
                    <p className={`text-sm m-0 leading-snug${failed ? ' font-mono' : ''}`}>{message}</p>
                </QuillLabeledRow>
            )}
        </div>
    )
}
