// No DORA band edge: a band on one person's or one team's lead time reads as a grade.

import { LemonCard, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type { DeliveryLeadTimeApi, DurationDistributionApi } from '../generated/api.schemas'
import { compactAgeLabel } from '../lib/format'
import { BoxPlotBucket, LeadTimeBoxPlot } from './LeadTimeBoxPlot'

function toBucket(label: string, distribution: DurationDistributionApi): BoxPlotBucket {
    return {
        label,
        count: distribution.pr_count,
        minSeconds: distribution.min_seconds,
        p05Seconds: distribution.p05_seconds,
        p25Seconds: distribution.p25_seconds,
        p50Seconds: distribution.p50_seconds,
        meanSeconds: distribution.mean_seconds,
        p75Seconds: distribution.p75_seconds,
        p95Seconds: distribution.p95_seconds,
        maxSeconds: distribution.max_seconds,
    }
}

export function LeadTimeComparisonCard({
    leadTime,
    scopeLabel,
    loading,
}: {
    leadTime: DeliveryLeadTimeApi | null | undefined
    scopeLabel: string
    loading: boolean
}): JSX.Element {
    const stages = leadTime
        ? [
              { key: 'open_to_deploy', title: 'Open to deploy', pair: leadTime.open_to_deploy },
              { key: 'open_to_merge', title: 'Open to merge', pair: leadTime.open_to_merge },
              { key: 'merge_to_deploy', title: 'Merge to deploy', pair: leadTime.merge_to_deploy },
          ]
        : []
    const headline = leadTime?.open_to_deploy.scope

    return (
        <LemonCard
            hoverEffect={false}
            className="flex flex-col p-4"
            data-attr="engineering-analytics-delivery-lead-time"
        >
            <h3 className="mb-1 text-xs font-semibold text-secondary">
                <Tooltip
                    title={
                        <div className="flex flex-col gap-1">
                            <div>
                                Pull requests merged in the window (bots and drafts excluded), each matched once to the
                                first successful deploy that contains its merge by the window end, in the environments
                                named under the headline. Open to merge includes draft time. The three stages use the
                                same pull requests. For each one, open to merge and merge to deploy add up to open to
                                deploy, but their medians do not.
                            </div>
                            <div>
                                Box: the middle half of the pull requests. Line: median. Dot: mean. Whiskers: 5th to
                                95th percentile. The time axis is logarithmic, so a few very slow pull requests don't
                                squash the rest.
                            </div>
                            <div>
                                Deploy failure share and recovery are not shown: one deploy ships many pull requests, so
                                neither belongs to one author or team. Health shows both for the repo.
                            </div>
                        </div>
                    }
                >
                    <span className="cursor-default">Lead time to deploy</span>
                </Tooltip>
            </h3>
            {loading ? (
                <LemonSkeleton className="h-56 w-full" />
            ) : !leadTime?.deploy_data_available ? (
                <div className="flex h-20 items-center text-xs text-secondary">
                    Lead time appears once the deployments and deployment statuses tables on this GitHub source are
                    synced.
                </div>
            ) : !headline || headline.pr_count === 0 ? (
                <div className="flex h-20 items-center text-xs text-secondary">
                    None of these pull requests reached a deploy in the window.
                </div>
            ) : (
                <>
                    <div className="flex flex-wrap items-baseline gap-2">
                        <span className="text-2xl font-semibold leading-none tabular-nums">
                            {compactAgeLabel(headline.p50_seconds)}
                        </span>
                        <span className="text-xs tabular-nums text-tertiary">
                            open to deploy, median · repo {compactAgeLabel(leadTime.open_to_deploy.repo.p50_seconds)}
                        </span>
                    </div>
                    <div className="mb-3 mt-1 text-[11px] tabular-nums text-tertiary">
                        {leadTime.deployed_merged_pr_count} of{' '}
                        {pluralize(leadTime.merged_pr_count, 'merged pull request')} matched to a deploy in{' '}
                        {leadTime.environment_scope}
                    </div>
                    <div className="@container">
                        <div className="grid grid-cols-1 gap-4 @min-[40rem]:grid-cols-3">
                            {stages.map((stage) => (
                                <div key={stage.key} className="min-w-0">
                                    <div className="text-[11px] font-semibold text-secondary">{stage.title}</div>
                                    <LeadTimeBoxPlot
                                        seriesKey={stage.key}
                                        seriesLabel={stage.title}
                                        buckets={[
                                            toBucket(scopeLabel, stage.pair.scope),
                                            toBucket('Repo', stage.pair.repo),
                                        ]}
                                        formatSeconds={compactAgeLabel}
                                        excludeOutliers
                                        horizontal
                                        logScale
                                        className="h-28"
                                        dataAttr={`engineering-analytics-delivery-${stage.key}`}
                                    />
                                </div>
                            ))}
                        </div>
                    </div>
                </>
            )}
        </LemonCard>
    )
}
