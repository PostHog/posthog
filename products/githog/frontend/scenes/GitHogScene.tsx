import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { GitHogRepository, gitHogReposLogic } from './gitHogReposLogic'

export const scene: SceneExport = {
    component: GitHogScene,
    logic: gitHogReposLogic,
}

export function GitHogScene(): JSX.Element {
    const { repositories, repositoriesLoading } = useValues(gitHogReposLogic)

    const columns: LemonTableColumns<GitHogRepository> = [
        {
            title: 'Repository',
            key: 'full_name',
            sticky: true,
            render: (_, repo) => (
                <LemonTableLink
                    to={urls.gitHogRepo(repo.owner, repo.name)}
                    title={repo.full_name}
                    description={`Owned by ${repo.owner}`}
                />
            ),
        },
        {
            title: 'GitHub',
            key: 'github',
            render: (_, repo) => (
                <Link to={`https://github.com/${repo.full_name}`} target="_blank">
                    View on GitHub
                </Link>
            ),
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name="GitHog"
                description="Repositories from your connected GitHub integration."
                resourceType={{ type: 'githog' }}
            />
            {!repositoriesLoading && repositories.length === 0 ? (
                <p className="text-muted">
                    No repositories found. Connect a GitHub integration in your project settings to see repositories
                    here.
                </p>
            ) : (
                <LemonTable
                    loading={repositoriesLoading}
                    columns={columns}
                    dataSource={repositories}
                    rowKey={(repo) => `${repo.integration_id}-${repo.id}`}
                    emptyState="No repositories"
                />
            )}
        </SceneContent>
    )
}

export default GitHogScene
