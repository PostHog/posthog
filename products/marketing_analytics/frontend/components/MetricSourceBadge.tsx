import { IconGitBranch } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import posthogIcon from 'public/posthog-icon.svg'

import type { OverviewMetricSource } from '../overview/overviewMetricConfiguration'

const SOURCE_DESCRIPTIONS: Record<OverviewMetricSource, string> = {
    platforms: 'Reported directly by your ad platforms and added together',
    posthog: 'Calculated from your PostHog event data',
}

export function MetricSourceBadge({ source }: { source: OverviewMetricSource }): JSX.Element {
    return (
        <Tooltip title={SOURCE_DESCRIPTIONS[source]}>
            <span
                className="inline-flex shrink-0 items-center"
                aria-label={SOURCE_DESCRIPTIONS[source]}
                data-attr={`marketing-metric-source-${source}`}
            >
                {source === 'posthog' ? (
                    <img src={posthogIcon} alt="" className="size-4" />
                ) : (
                    <IconGitBranch className="size-4 text-secondary" />
                )}
            </span>
        </Tooltip>
    )
}
