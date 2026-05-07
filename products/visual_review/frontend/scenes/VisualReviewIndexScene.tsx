import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { visualReviewIndexSceneLogic } from './visualReviewIndexSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewIndexScene,
    logic: visualReviewIndexSceneLogic,
}

// /visual_review forwards straight to the first repo's Runs page once the
// repo list lands. There is no picker page — the in-header repo switcher
// covers the multi-repo case. Only the empty state and the brief loader
// state ever paint.
export function VisualReviewIndexScene(): JSX.Element {
    const { repos, reposLoading } = useValues(visualReviewIndexSceneLogic)

    useEffect(() => {
        if (!reposLoading && repos.length >= 1) {
            router.actions.replace(urls.visualReviewRepoRuns(repos[0].id))
        }
    }, [reposLoading, repos])

    if (reposLoading || repos.length >= 1) {
        return (
            <SceneContent>
                <SceneTitleSection name="Visual review" resourceType={{ type: 'visual_review' }} />
                <LemonSkeleton className="h-32 w-full max-w-2xl" />
            </SceneContent>
        )
    }

    return (
        <SceneContent>
            <SceneTitleSection name="Visual review" resourceType={{ type: 'visual_review' }} />
            <div className="max-w-2xl">
                <p className="text-muted">
                    No visual review repos yet. Connect one from <Link to={urls.visualReviewSettings()}>Settings</Link>{' '}
                    to get started.
                </p>
                <LemonButton type="primary" to={urls.visualReviewSettings()}>
                    Open settings
                </LemonButton>
            </div>
        </SceneContent>
    )
}

export default VisualReviewIndexScene
