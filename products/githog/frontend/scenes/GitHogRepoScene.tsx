import { useValues } from 'kea'

import { LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { GitHogPullRequest, GitHogRepoLogicProps, gitHogRepoLogic } from './gitHogRepoLogic'

export const scene: SceneExport<GitHogRepoLogicProps> = {
    component: GitHogRepoScene,
    logic: gitHogRepoLogic,
    paramsToProps: ({ params: { owner, name } }) => ({
        owner: decodeURIComponent(owner ?? ''),
        name: decodeURIComponent(name ?? ''),
    }),
}

export function GitHogRepoScene({ owner, name }: GitHogRepoLogicProps): JSX.Element {
    const { pullRequests, pullRequestsLoading } = useValues(gitHogRepoLogic({ owner, name }))
    const repository = `${owner}/${name}`

    const columns: LemonTableColumns<GitHogPullRequest> = [
        {
            title: '#',
            key: 'number',
            width: 80,
            render: (_, pr) => (
                <Link to={urls.gitHogPullRequest(owner, name, pr.number)}>
                    <span className="font-mono">#{pr.number}</span>
                </Link>
            ),
        },
        {
            title: 'Title',
            key: 'title',
            render: (_, pr) => <Link to={urls.gitHogPullRequest(owner, name, pr.number)}>{pr.title}</Link>,
        },
        {
            title: 'GitHub',
            key: 'github',
            render: (_, pr) => (
                <Link to={pr.url} target="_blank">
                    View on GitHub
                </Link>
            ),
        },
        {
            title: 'State',
            key: 'state',
            render: (_, pr) => <LemonTag type={pr.state === 'open' ? 'success' : 'default'}>{pr.state}</LemonTag>,
        },
        {
            title: 'Branch',
            key: 'head_branch',
            render: (_, pr) => (
                <span className="text-muted font-mono text-xs">
                    {pr.head_branch} → {pr.base_branch}
                </span>
            ),
        },
        {
            title: 'Updated',
            key: 'updated_at',
            render: (_, pr) => <TZLabel time={pr.updated_at} />,
        },
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={repository}
                description="Open pull requests in this repository."
                resourceType={{ type: 'githog' }}
            />
            <LemonTable
                loading={pullRequestsLoading}
                columns={columns}
                dataSource={pullRequests}
                rowKey={(pr) => pr.number}
                emptyState="No open pull requests"
            />
        </SceneContent>
    )
}

export default GitHogRepoScene
