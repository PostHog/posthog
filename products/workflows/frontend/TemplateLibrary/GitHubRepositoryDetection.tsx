import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { githubIntegrationLogic } from 'lib/integrations/githubIntegrationLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import { brandedStarterLogic } from './brandedStarterLogic'
import type { GitHubBrandDetectionProps } from './GitHubBrandDetection'
import { likeliestRepository } from './likeliestRepository'

export function GitHubRepositoryDetection({
    integrationId,
    logicProps,
    busyReason,
}: GitHubBrandDetectionProps & { integrationId: number }): JSX.Element {
    const { repositories, repositoriesLoaded, repositoriesLoadFailed } = useValues(
        githubIntegrationLogic({ id: integrationId })
    )
    const { loadRepositories } = useActions(githubIntegrationLogic({ id: integrationId }))
    const { currentTeam } = useValues(teamLogic)
    const { currentProject } = useValues(projectLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { isDetectingFromGitHub, githubDetectionError } = useValues(brandedStarterLogic(logicProps))
    const { detectBrandFromGitHub } = useActions(brandedStarterLogic(logicProps))
    const [chosenRepository, setChosenRepository] = useState<string | null | undefined>(undefined)
    const detectRef = useRef<HTMLButtonElement>(null)
    useEffect(() => detectRef.current?.focus(), [])
    const suggestedRepository = useMemo(
        () =>
            likeliestRepository(repositories, {
                appUrls: currentTeam?.app_urls ?? [],
                projectName: currentProject?.name ?? '',
                organizationName: currentOrganization?.name ?? '',
            }),
        [repositories, currentTeam?.app_urls, currentProject?.name, currentOrganization?.name]
    )
    const repository = chosenRepository === undefined ? (suggestedRepository?.full_name ?? null) : chosenRepository

    if (repositoriesLoadFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: loadRepositories }}>
                Could not load your GitHub repositories.
            </LemonBanner>
        )
    }
    if (repositoriesLoaded && repositories.length === 0) {
        return (
            <LemonBanner
                type="info"
                action={{ children: 'Check again', onClick: loadRepositories }}
                data-attr="email-branded-starter-github-no-repositories"
            >
                The PostHog GitHub app cannot see any repositories.{' '}
                <Link to={urls.settings('environment-integrations')} target="_blank">
                    Check which repositories it can access
                </Link>
                .
            </LemonBanner>
        )
    }
    return (
        <div className="space-y-2">
            <div className="flex items-end gap-2">
                <LemonField.Pure label="GitHub repository" className="flex-1 min-w-0">
                    <GitHubRepositoryPicker
                        integrationId={integrationId}
                        valueKey="full_name"
                        value={repository?.toLowerCase() ?? ''}
                        onChange={(key) => setChosenRepository(fullNameOf(repositories, key))}
                    />
                </LemonField.Pure>
                <LemonButton
                    ref={detectRef}
                    data-attr="email-branded-starter-github-detect"
                    type="secondary"
                    loading={isDetectingFromGitHub}
                    disabledReason={busyReason ?? (repository ? undefined : 'Choose a repository')}
                    onClick={() => repository && detectBrandFromGitHub(integrationId, repository)}
                >
                    Detect
                </LemonButton>
            </div>
            {githubDetectionError && <LemonBanner type="error">{githubDetectionError}</LemonBanner>}
        </div>
    )
}

function fullNameOf(repositories: GitHubRepoApi[], pickerKey: string | null): string | null {
    return repositories.find((repository) => repository.full_name.toLowerCase() === pickerKey)?.full_name ?? null
}
