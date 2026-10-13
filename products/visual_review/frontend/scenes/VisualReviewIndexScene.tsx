import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { visualReviewIndexSceneLogic } from './visualReviewIndexSceneLogic'

export const scene: SceneExport = {
    component: VisualReviewIndexScene,
    logic: visualReviewIndexSceneLogic,
    productKey: ProductKey.VISUAL_REVIEW,
}

// /visual_review is a pure forwarder, so this renders only while the repo list is in flight,
// or when it failed and there is nothing to forward to. The forward itself lives in the logic.
export function VisualReviewIndexScene(): JSX.Element {
    const { reposLoadFailed } = useValues(visualReviewIndexSceneLogic)
    const { loadRepos } = useActions(visualReviewIndexSceneLogic)

    return (
        <SceneContent>
            <SceneTitleSection name="Visual review" resourceType={{ type: 'visual_review' }} />
            {reposLoadFailed ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: loadRepos }} className="max-w-2xl">
                    Couldn't load your connected repos.
                </LemonBanner>
            ) : (
                <LemonSkeleton className="h-32 w-full max-w-2xl" />
            )}
        </SceneContent>
    )
}

export default VisualReviewIndexScene
