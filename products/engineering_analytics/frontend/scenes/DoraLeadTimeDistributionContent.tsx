import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { LeadTimeBoxPlot } from '../components/LeadTimeBoxPlot'
import { compactAgeLabel } from '../lib/format'
import { doraLogic } from './doraLogic'
import { DoraUnattributedNotice } from './DoraUnattributedNotice'

export function DoraLeadTimeDistributionContent(): JSX.Element {
    const {
        dora,
        doraLoading,
        githubTeam,
        openToDeployBuckets,
        openToMergeBuckets,
        boxPlotBuckets,
        showAllLeadTimeStages,
        excludeOutliers,
    } = useValues(doraLogic)
    const { toggleLeadTimeStages } = useActions(doraLogic)
    const leadTimeStages = [
        {
            title: 'Open to deploy',
            seriesKey: 'open_to_deploy',
            seriesLabel: 'Open to deploy',
            buckets: openToDeployBuckets,
            dataAttr: 'open-to-deploy-box-plot',
            wrapperDataAttr: 'engineering-analytics-dora-open-to-deploy-box-plot',
        },
        {
            title: 'Open to merge',
            seriesKey: 'open_to_merge',
            seriesLabel: 'Open to merge',
            buckets: openToMergeBuckets,
            dataAttr: 'open-to-merge-box-plot',
            wrapperDataAttr: 'engineering-analytics-dora-open-to-merge-box-plot',
        },
        {
            title: 'Merge to deploy',
            seriesKey: 'merge_to_deploy',
            seriesLabel: 'Merge to deploy',
            buckets: boxPlotBuckets,
            dataAttr: 'merge-to-deploy-box-plot',
            wrapperDataAttr: 'engineering-analytics-dora-box-plot',
        },
    ]
    const membershipDataMissing = !!githubTeam && !!dora && !dora.has_membership_data

    if (doraLoading && !dora) {
        return <LemonSkeleton className="h-40 w-full" />
    }
    if (!openToDeployBuckets.some((bucket) => bucket.count > 0)) {
        return (
            <div
                className="py-8 text-center text-sm text-secondary"
                data-attr="engineering-analytics-dora-unattributed-empty"
            >
                {membershipDataMissing
                    ? 'Team membership data is not synced, so the team filter cannot be applied.'
                    : 'No PRs could be matched to successful deployments in this window. Try a wider date range or check that pull requests and deployment statuses have synced.'}
            </div>
        )
    }

    return (
        <>
            <div className="flex flex-col gap-4">
                {(showAllLeadTimeStages ? leadTimeStages : leadTimeStages.slice(0, 1)).map((stage) => (
                    <div key={stage.seriesKey} data-attr={stage.wrapperDataAttr}>
                        <h3 className="m-0 mb-1 text-xs font-semibold text-secondary">{stage.title}</h3>
                        <LeadTimeBoxPlot
                            seriesKey={stage.seriesKey}
                            seriesLabel={stage.seriesLabel}
                            buckets={stage.buckets}
                            formatSeconds={compactAgeLabel}
                            excludeOutliers={excludeOutliers}
                            dataAttr={stage.dataAttr}
                        />
                    </div>
                ))}
            </div>
            <div className="mt-2">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={showAllLeadTimeStages ? <IconChevronDown /> : <IconChevronRight />}
                    onClick={toggleLeadTimeStages}
                    data-attr="engineering-analytics-dora-stage-toggle"
                >
                    {showAllLeadTimeStages
                        ? 'Hide open to merge and merge to deploy'
                        : 'Show open to merge and merge to deploy'}
                </LemonButton>
            </div>
            <DoraUnattributedNotice />
        </>
    )
}
