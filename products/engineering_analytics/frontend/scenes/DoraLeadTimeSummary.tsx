import { useValues } from 'kea'

import { Section } from '../components/Section'
import { WindowComparisonCard } from '../components/WindowComparisonCard'
import { compactAgeLabel } from '../lib/format'
import { doraLogic } from './doraLogic'

export function DoraLeadTimeSummary(): JSX.Element {
    const { dora, doraLoading, githubTeam } = useValues(doraLogic)
    const membershipDataMissing = !!githubTeam && !!dora && !dora.has_membership_data

    return (
        <Section id="lead-time" title="Lead time">
            <WindowComparisonCard
                title="Open to deploy"
                tooltip={`Median from a PR's open to the first successful deployment containing it in any selected environment, over ${dora?.deployed_pr_count ?? 0} deployed PRs (bots and drafts excluded). Each PR counts once. The box plots split it into open to merge and merge to deploy.`}
                value={dora?.median_open_to_deploy_seconds}
                previousValue={dora?.median_open_to_deploy_seconds_prev}
                formatValue={compactAgeLabel}
                goodWhenDown
                emptyText={
                    membershipDataMissing
                        ? 'Sync team membership to apply this filter.'
                        : 'No PRs could be matched to successful deployments in this window. Try a wider date range or check the source sync.'
                }
                loading={doraLoading && !dora}
            />
        </Section>
    )
}
