import { useActions, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
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

// This scene is a pure forwarder, so it renders only while the lookup is in flight,
// or when the lookup failed and there is nothing to forward to. The forward itself lives in the logic.
export function VisualReviewIndexScene(): JSX.Element {
    const { forwardFailure, forwardRoute } = useValues(visualReviewIndexSceneLogic)
    const { forward } = useActions(visualReviewIndexSceneLogic)

    if (forwardFailure === 'not_found') {
        return <NotFound object={forwardRoute?.kind === 'run' ? 'visual review run' : 'visual review repo'} />
    }

    return (
        <SceneContent>
            <SceneTitleSection name="Visual review" resourceType={{ type: 'visual_review' }} />
            {forwardFailure === 'load_failed' && forwardRoute ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => forward(forwardRoute) }}
                    className="max-w-2xl"
                >
                    Couldn't load your connected repos.
                </LemonBanner>
            ) : (
                <LemonSkeleton className="h-32 w-full max-w-2xl" />
            )}
        </SceneContent>
    )
}

export default VisualReviewIndexScene
