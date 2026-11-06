import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { Section } from '../components/Section'
import { percent } from '../lib/format'
import { DoraLeadTimeDistributionContent } from './DoraLeadTimeDistributionContent'
import { DoraLeadTimeSummary } from './DoraLeadTimeSummary'
import { UNATTRIBUTED_WARNING_SHARE, doraLogic } from './doraLogic'

export function DoraLeadTimeSection(): JSX.Element {
    const { dora, doraLoading, githubTeam, githubTeamOptions, excludeOutliers, showUnattributedWarning } =
        useValues(doraLogic)
    const { setGithubTeam, setExcludeOutliers } = useActions(doraLogic)

    return (
        <Section
            id="lead-time"
            title="Lead time"
            right={
                <div className="flex flex-wrap items-center justify-end gap-2">
                    <LemonSelect
                        size="small"
                        value={githubTeam}
                        onChange={setGithubTeam}
                        options={githubTeamOptions}
                        disabledReason={
                            dora?.has_membership_data ? undefined : 'Sync team membership to filter lead time by team'
                        }
                        data-attr="engineering-analytics-dora-team-select"
                    />
                    <LemonSwitch
                        size="small"
                        bordered
                        label="Exclude outliers"
                        checked={excludeOutliers}
                        onChange={setExcludeOutliers}
                        data-attr="engineering-analytics-dora-exclude-outliers"
                    />
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                {!doraLoading && showUnattributedWarning && (
                    <div data-attr="engineering-analytics-dora-unattributed">
                        <LemonBanner type="warning">
                            More than {percent(UNATTRIBUTED_WARNING_SHARE)} of PRs merged in this window have no
                            successful deployment attributed in the selected environments. Lead-time results exclude
                            unmatched PRs. Check the source sync or allow more time for deployments.
                        </LemonBanner>
                    </div>
                )}
                <DoraLeadTimeSummary />
                <div data-attr="engineering-analytics-dora-grouped-charts">
                    {doraLoading ? <LemonSkeleton className="h-40 w-full" /> : <DoraLeadTimeDistributionContent />}
                </div>
            </div>
        </Section>
    )
}
