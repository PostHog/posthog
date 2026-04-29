import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { visualReviewIndexSceneLogic } from './visualReviewIndexSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewIndexScene,
    logic: visualReviewIndexSceneLogic,
}

export function VisualReviewIndexScene(): JSX.Element {
    const { repos, reposLoading } = useValues(visualReviewIndexSceneLogic)
    const { loadRepos } = useActions(visualReviewIndexSceneLogic)

    // Once the repo list arrives: forward immediately if there's exactly one,
    // otherwise render a picker. The afterMount hook handles the case where
    // repos were already loaded; this effect handles first load.
    useEffect(() => {
        if (!reposLoading && repos.length === 1) {
            router.actions.replace(urls.visualReviewRepoRuns(repos[0].id))
        }
    }, [reposLoading, repos])

    if (reposLoading) {
        return (
            <SceneContent>
                <SceneTitleSection name="Visual review" resourceType={{ type: 'visual_review' }} />
                <LemonSkeleton className="h-32 w-full max-w-2xl" />
            </SceneContent>
        )
    }

    if (repos.length === 0) {
        return (
            <SceneContent>
                <SceneTitleSection name="Visual review" resourceType={{ type: 'visual_review' }} />
                <div className="max-w-2xl">
                    <p className="text-muted">
                        No visual review repos yet. Connect one from{' '}
                        <Link to={urls.visualReviewSettings()}>Settings</Link> to get started.
                    </p>
                    <LemonButton type="primary" to={urls.visualReviewSettings()}>
                        Open settings
                    </LemonButton>
                </div>
            </SceneContent>
        )
    }

    // Multi-repo case — render a small picker. The single-repo case is
    // already on its way to the workspace via the effect above; this branch
    // shouldn't render in practice for that case.
    return (
        <SceneContent>
            <SceneTitleSection
                name="Visual review"
                resourceType={{ type: 'visual_review' }}
                actions={
                    <LemonButton type="secondary" onClick={loadRepos} loading={reposLoading}>
                        Refresh
                    </LemonButton>
                }
            />
            <div className="flex flex-col gap-2 max-w-2xl">
                <h3 className="m-0 text-base">Pick a repo</h3>
                {repos.map((repo) => (
                    <Link
                        key={repo.id}
                        to={urls.visualReviewRepoRuns(repo.id)}
                        className="flex items-center justify-between border border-border rounded p-3 bg-bg-light hover:border-primary transition-colors"
                    >
                        <span className="font-mono text-sm">{repo.repo_full_name}</span>
                        <span className="text-xs text-muted">connected {dayjs(repo.created_at).fromNow()}</span>
                    </Link>
                ))}
            </div>
        </SceneContent>
    )
}

export default VisualReviewIndexScene
