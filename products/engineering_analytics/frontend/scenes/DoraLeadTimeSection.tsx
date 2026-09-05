import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { ScopePanel } from '../components/ScopePanel'
import { DoraLeadTimeDistributions } from './DoraLeadTimeDistributions'
import { DoraLeadTimeSummary } from './DoraLeadTimeSummary'
import { doraLogic } from './doraLogic'

export function DoraLeadTimeSection(): JSX.Element {
    const { dora, doraLoading, githubTeam, githubTeamOptions } = useValues(doraLogic)
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
            <DoraLeadTimeSummary />
            <DoraLeadTimeDistributions />
        </ScopePanel>
    )
}
