import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'

import { reportGithubAccessLogic } from '../../logics/reportGithubAccessLogic'
import { SignalReport } from '../../types'

export function ReportRepositorySelection({
    report,
    surface,
    onConnect,
    integrationDisabledReason,
}: {
    report: SignalReport
    surface: 'detail_pane' | 'triage_mode'
    onConnect: () => void
    integrationDisabledReason?: string
}): JSX.Element {
    const logic = reportGithubAccessLogic({ report, surface })
    const { repositoryIntegrationId, selectedRepository, githubIntegrations } = useValues(logic)
    const { setSelectedRepository, setSelectedIntegrationId } = useActions(logic)
    return (
        <div className="flex flex-col gap-2">
            <span className="text-xs font-semibold text-tertiary">Select a repository to implement this report</span>
            {githubIntegrations.length > 1 && (
                <LemonSelect
                    value={repositoryIntegrationId}
                    options={githubIntegrations.map((integration) => ({
                        value: integration.id,
                        label: integration.display_name,
                    }))}
                    onChange={(id) => id != null && setSelectedIntegrationId(id)}
                    disabledReason={integrationDisabledReason}
                    aria-label="GitHub account"
                />
            )}
            {repositoryIntegrationId !== null ? (
                <GitHubRepositoryPicker
                    integrationId={repositoryIntegrationId}
                    value={selectedRepository}
                    valueKey="full_name"
                    onChange={setSelectedRepository}
                    selectOnlyOption
                />
            ) : (
                <LemonButton type="secondary" onClick={onConnect} data-attr="inbox-report-select-repository-connect">
                    Connect GitHub
                </LemonButton>
            )}
        </div>
    )
}
