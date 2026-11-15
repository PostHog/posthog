import { LemonCard, LemonTag, type LemonTagType } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { ExperimentVariantsReadoutApi } from '../../../generated/api.schemas'

const STATUS_TAG_TYPE: Record<string, LemonTagType> = {
    running: 'success',
    paused: 'warning',
    draft: 'default',
}

// The same gray the experiment pages use for a variant without a series color.
const UNATTRIBUTED_COLOR = 'var(--muted)'

export interface VariantsExperimentStripProps {
    readout: ExperimentVariantsReadoutApi
    variantColors: Record<string, string>
}

/** The watched experiment, where it is in its run, and how the observations split across variants. */
export function VariantsExperimentStrip({ readout, variantColors }: VariantsExperimentStripProps): JSX.Element {
    const { experiment, window: observationWindow, variants, unattributed_count } = readout
    const total = observationWindow.total_observations
    const segments = [
        ...variants.map((variant) => ({
            key: variant.key,
            label: variant.key,
            count: variant.observations,
            color: variantColors[variant.key],
        })),
        { key: 'unattributed', label: 'No variant', count: unattributed_count, color: UNATTRIBUTED_COLOR },
    ].filter((segment) => segment.count > 0)

    return (
        <LemonCard hoverEffect={false} className="p-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
            <div className="min-w-0 flex flex-wrap items-center gap-2">
                {experiment ? (
                    <>
                        <Link to={urls.experiment(experiment.id)} className="font-semibold truncate">
                            {experiment.name}
                        </Link>
                        <LemonTag type={STATUS_TAG_TYPE[experiment.status] ?? 'default'} className="capitalize">
                            {experiment.status}
                        </LemonTag>
                        {experiment.current_day != null && (
                            <span className="text-sm text-muted">
                                {experiment.planned_duration_days
                                    ? `Day ${experiment.current_day} of ${Math.round(experiment.planned_duration_days)}`
                                    : `Day ${experiment.current_day}`}
                            </span>
                        )}
                    </>
                ) : (
                    <span className="text-sm text-muted">
                        The experiment was deleted. These counts cover what the scanner saw before.
                    </span>
                )}
            </div>
            <div className="w-full @3xl:w-auto @3xl:min-w-80 space-y-1.5">
                {total > 0 && (
                    <div className="flex h-2 w-full overflow-hidden rounded-full bg-fill-secondary">
                        {segments.map((segment) => (
                            <div
                                key={segment.key}
                                // Widths and colors come from the data, so they can't be Tailwind classes.
                                style={{ width: `${(segment.count / total) * 100}%`, backgroundColor: segment.color }}
                            />
                        ))}
                    </div>
                )}
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                    {segments.map((segment) => (
                        <span key={segment.key} className="inline-flex items-center gap-1">
                            <span
                                className="inline-block size-2 rounded-sm"
                                style={{ backgroundColor: segment.color }}
                                aria-hidden
                            />
                            <span className="text-muted">{segment.label}</span>
                            <span className="font-semibold tabular-nums">{segment.count}</span>
                        </span>
                    ))}
                    <span className="text-muted">{pluralize(total, 'observation')} in total</span>
                </div>
            </div>
        </LemonCard>
    )
}
