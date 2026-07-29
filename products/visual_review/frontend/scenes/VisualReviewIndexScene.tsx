import { useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { visualReviewIndexSceneLogic } from './visualReviewIndexSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewIndexScene,
    logic: visualReviewIndexSceneLogic,
    productKey: ProductKey.VISUAL_REVIEW,
}

// /visual_review is a pure forwarder: with a repo connected it goes to that repo's
// Runs page (the in-header repo switcher covers multi-repo), and with none it goes
// to Settings, where connecting a repo is the only meaningful action.
export function VisualReviewIndexScene(): JSX.Element {
    const { repos, reposLoading } = useValues(visualReviewIndexSceneLogic)

    useEffect(() => {
        if (reposLoading) {
            return
        }
        if (repos.length >= 1) {
            router.actions.replace(urls.visualReviewRepoRuns(repos[0].id))
        } else {
            router.actions.replace(urls.visualReviewSettings())
        }
    }, [reposLoading, repos])

    return (
        <SceneContent>
            <SceneTitleSection name="Visual review" resourceType={{ type: 'visual_review' }} />
            <LemonSkeleton className="h-32 w-full max-w-2xl" />
        </SceneContent>
    )
}

export default VisualReviewIndexScene
