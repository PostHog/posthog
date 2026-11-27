import { IconGitBranch } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { Tooltip as QuillTooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import posthogIcon from 'public/posthog-icon.svg'

import type { OverviewMetricSource } from '../overview/overviewMetricConfiguration'

const SOURCE_DESCRIPTIONS: Record<OverviewMetricSource, string> = {
    platforms: 'Reported directly by your ad platforms and added together',
    posthog: 'Calculated from your PostHog event data',
}

export function MetricSourceBadge({ source }: { source: OverviewMetricSource }): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <QuillTooltip>
                <TooltipTrigger
                    render={
                        <span
                            tabIndex={0}
                            className="inline-flex shrink-0 items-center"
                            aria-label={SOURCE_DESCRIPTIONS[source]}
                            data-attr={`marketing-metric-source-${source}`}
                        />
                    }
                >
                    {source === 'posthog' ? (
                        <img src={posthogIcon} alt="" className="size-4" />
                    ) : (
                        <IconGitBranch className="size-4 text-muted-foreground" />
                    )}
                </TooltipTrigger>
                <TooltipContent>{SOURCE_DESCRIPTIONS[source]}</TooltipContent>
            </QuillTooltip>
        )
    }

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
