import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'

import { ScopePanel } from '../components/ScopePanel'
import { DoraLeadTimeDistributions } from './DoraLeadTimeDistributions'
import { DoraLeadTimeSummary } from './DoraLeadTimeSummary'
import { doraLogic } from './doraLogic'

export function DoraLeadTimeSection(): JSX.Element {
    const { dora, doraLoading, githubTeam, githubTeamOptions, showUnattributedWarning } = useValues(doraLogic)
    const { setGithubTeam } = useActions(doraLogic)

    return (
        <ScopePanel
            busy={doraLoading && !!dora}
            controls={
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
            }
        >
            {showUnattributedWarning && (
                <div data-attr="engineering-analytics-dora-unattributed">
                    <LemonBanner type="warning">
                        More than 10% of PRs merged in this window have no successful deployment attributed in the
                        selected environments. Lead-time results exclude unmatched PRs. Check the source sync or allow
                        more time for deployments.
                    </LemonBanner>
                </div>
            )}
            <DoraLeadTimeSummary />
            <DoraLeadTimeDistributions />
        </ScopePanel>
    )
}
