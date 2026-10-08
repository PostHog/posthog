import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'

import { ObservationResultSummary } from '../../../components/ObservationCard'
import { ObservationThumbnail } from '../../../components/ObservationThumbnail'
import type { ReplayObservationApi } from '../../../generated/api.schemas'
import { observationDetailUrl } from '../../../observations/replayObservationLogic'

export interface VariantObservationRowProps {
    observation: ReplayObservationApi
}

/** One recent observation of a variant: its summary, who it was, and when. */
export function VariantObservationRow({ observation }: VariantObservationRowProps): JSX.Element {
    const person = observation.recording_subject_email || observation.distinct_id
    return (
        <Link
            to={observationDetailUrl(observation.id, {})}
            subtle
            className="flex gap-3 rounded p-1 -m-1 hover:bg-fill-highlight-50"
            data-attr="vision-variant-latest-observation"
        >
            <div className="hidden @md:block w-24 shrink-0">
                <ObservationThumbnail observation={observation} className="rounded" />
            </div>
            <div className="min-w-0 flex-1 space-y-0.5">
                <div className="text-sm line-clamp-3">
                    <ObservationResultSummary observation={observation} />
                </div>
                <div className="flex flex-wrap items-center gap-1 text-xs text-muted">
                    {person && <span className="truncate min-w-0">{person}</span>}
                    {person && <span aria-hidden>·</span>}
                    <TZLabel time={observation.created_at} className="shrink-0" />
                </div>
            </div>
        </Link>
    )
}
