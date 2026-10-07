import { LemonCard } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { VariantReadoutApi } from '../../../generated/api.schemas'
import { observationDetailUrl } from '../../../observations/replayObservationLogic'
import { VariantObservationRow } from './VariantObservationRow'

export interface VariantCardProps {
    variant: VariantReadoutApi
    color: string
    /** Whether the scanner samples variants evenly, which makes counts follow sampling, not traffic. */
    balanced: boolean
    observationsUrl: string
    onOpenObservations: () => void
}

/** One variant: live counts, its sampling rate, the analysis themes, and its newest observations. */
export function VariantCard({
    variant,
    color,
    balanced,
    observationsUrl,
    onOpenObservations,
}: VariantCardProps): JSX.Element {
    const stats = [
        pluralize(variant.observations, 'observation'),
        pluralize(variant.distinct_people, 'person', 'people'),
        variant.median_session_duration_s != null
            ? `median session ${humanFriendlyDuration(variant.median_session_duration_s)}`
            : null,
    ].filter(Boolean)

    return (
        <LemonCard hoverEffect={false} className="p-0 flex flex-col" data-attr="vision-variant-card">
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b px-4 py-3">
                <span className="flex min-w-0 items-center gap-2">
                    {/* The color comes from the variant's series index, so it can't be a Tailwind class. */}
                    <span className="inline-block size-2.5 shrink-0 rounded-sm" style={{ backgroundColor: color }} />
                    <span className="truncate font-semibold">{variant.key}</span>
                </span>
                <span className="text-xs text-muted">{stats.join(' · ')}</span>
            </div>

            {variant.sampling_rate != null && (
                <div className="px-4 pt-3 text-xs text-muted">
                    <Tooltip
                        title={
                            balanced
                                ? 'The scanner samples each variant to about the same number of sessions, so a small variant gets a higher rate. Counts follow sampling, not traffic.'
                                : 'The scanner samples every variant at the same rate, so counts follow traffic.'
                        }
                    >
                        <span className="cursor-help underline decoration-dotted underline-offset-2">
                            {`Sampled at ${percentage(variant.sampling_rate, 1)} of sessions`}
                        </span>
                    </Tooltip>
                </div>
            )}

            {variant.digest && variant.digest.length > 0 && (
                <div className="px-4 pt-3 space-y-1.5">
                    <div className="text-xs font-semibold uppercase text-muted">Themes</div>
                    <ul className="m-0 list-disc space-y-1 pl-5">
                        {variant.digest.map((line) => (
                            <li key={line.theme} className="text-sm">
                                <span>{line.statement}</span>{' '}
                                <span className="text-muted">
                                    {variant.analysis_observations != null
                                        ? `(${line.count} of ${variant.analysis_observations})`
                                        : `(${line.count})`}
                                </span>
                                {line.example_observation_ids.length > 0 && (
                                    <span className="ml-1 text-xs">
                                        {line.example_observation_ids.map((id, index) => (
                                            <Link
                                                key={id}
                                                to={observationDetailUrl(id, {})}
                                                className="ml-1"
                                                data-attr="vision-variant-theme-example"
                                            >
                                                {`Example ${index + 1}`}
                                            </Link>
                                        ))}
                                    </span>
                                )}
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            <div className="flex-1 px-4 py-3 space-y-2">
                <div className="text-xs font-semibold uppercase text-muted">Latest observations</div>
                {variant.latest_observations.length > 0 ? (
                    <div className="flex flex-col gap-3">
                        {variant.latest_observations.map((observation) => (
                            <VariantObservationRow key={observation.id} observation={observation} />
                        ))}
                    </div>
                ) : (
                    <p className="m-0 text-sm text-muted">No observations for this variant yet.</p>
                )}
            </div>

            {variant.observations > 0 && (
                <div className="border-t px-4 py-2">
                    <Link
                        to={observationsUrl}
                        onClick={onOpenObservations}
                        className="text-sm"
                        data-attr="vision-variant-view-observations"
                    >
                        {`View all ${pluralize(variant.observations, 'observation')}`}
                    </Link>
                </div>
            )}
        </LemonCard>
    )
}
