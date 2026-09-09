import { Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import posthog from 'lib/posthog-typed'
import { urls } from 'scenes/urls'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { ObservationResultSummary } from './ObservationCard'

interface ObservationPreviewCardProps {
    observation: ReplayObservationApi
    /** Zero-based place in the rail, captured so we can see how deep people read. */
    position: number
}

/** Compact preview of one observation for the scanners highlights view rails. Lighter than
 * `ObservationDockCard`: no retry, progress, or reasoning, just the result at a glance. */
export function ObservationPreviewCard({ observation, position }: ObservationPreviewCardProps): JSX.Element {
    return (
        <Link
            to={urls.replayVisionObservation(observation.id)}
            className="w-72 shrink-0 flex flex-col gap-2 border rounded bg-bg-light p-3 text-default hover:bg-surface-secondary"
            data-attr="vision-highlight-observation-card"
            onClick={() => {
                posthog.capture('replay_vision_highlight_observation_clicked', {
                    scanner_id: observation.scanner_id,
                    observation_id: observation.id,
                    position,
                })
            }}
        >
            <div className="text-sm min-h-10 overflow-hidden">
                <ObservationResultSummary observation={observation} />
            </div>
            <div className="flex items-center justify-between gap-2 text-xs text-muted mt-auto">
                <span className="truncate">{observation.recording_subject_email || observation.distinct_id || ''}</span>
                <TZLabel time={observation.created_at} className="shrink-0" />
            </div>
        </Link>
    )
}
