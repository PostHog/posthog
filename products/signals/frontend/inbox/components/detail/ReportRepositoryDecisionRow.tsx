import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { resolveTeamGitHubIntegration } from 'lib/integrations/GitHubIntegrationHelpers'
import { githubIntegrationLogic } from 'lib/integrations/githubIntegrationLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import type { LemonSelectOptionLeaf } from 'lib/lemon-ui/LemonSelect'

import type { ReportDecisionAttribution } from '../../utils/reportDecisions'
import { ReportDecisionRow } from './ReportDecisionRow'

interface ReportRepositoryDecisionRowProps {
    repository: string
    attribution: ReportDecisionAttribution | null
    onChange?: (repository: string) => void
    saving?: boolean
}

/**
 * Offers the repositories the project's GitHub connection reaches, the same set the repository
 * endpoint accepts. Read-only when the project has no GitHub connection to pick from.
 */
export function ReportRepositoryDecisionRow(props: ReportRepositoryDecisionRowProps): JSX.Element {
    useMountedLogic(integrationsLogic)
    const { githubIntegrations } = useValues(integrationsLogic)
    const integration = resolveTeamGitHubIntegration(githubIntegrations)

    if (!integration || !props.onChange) {
        return (
            <ReportDecisionRow
                label="Repository"
                value={props.repository}
                attribution={props.attribution}
                data-attr="report-repository-select"
            />
        )
    }
    return <RepositoryPicker {...props} onChange={props.onChange} integrationId={integration.id} />
}

function RepositoryPicker({
    repository,
    attribution,
    onChange,
    saving = false,
    integrationId,
}: ReportRepositoryDecisionRowProps & { onChange: (repository: string) => void; integrationId: number }): JSX.Element {
    const logic = githubIntegrationLogic({ id: integrationId })
    const { repositories, repositoriesLoading } = useValues(logic)
    const { loadRepositories } = useActions(logic)

    const options = useMemo((): LemonSelectOptionLeaf<string>[] => {
        // Archived repositories accept no changes, so the endpoint rejects them. Values are lowercased
        // to match the stored selection, while labels keep GitHub's casing.
        const reachable = repositories
            .filter((repo) => !repo.archived)
            .map((repo) => ({ value: repo.full_name.toLowerCase(), label: repo.full_name }))
        return reachable.some((option) => option.value === repository)
            ? reachable
            : [{ value: repository, label: repository }, ...reachable]
    }, [repositories, repository])

    return (
        <ReportDecisionRow<string>
            label="Repository"
            value={repository}
            attribution={attribution}
            options={options}
            onChange={onChange}
            saving={saving}
            optionsLoading={repositoriesLoading}
            searchPlaceholder="Search repositories"
            // The list pages through every repository the connection reaches, so it loads on first open
            // rather than with every report.
            onMenuOpen={() => {
                if (!repositoriesLoading && repositories.length === 0) {
                    loadRepositories()
                }
            }}
            data-attr="report-repository-select"
        />
    )
}
