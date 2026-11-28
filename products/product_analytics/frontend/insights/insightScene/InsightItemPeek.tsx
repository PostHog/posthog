import { SceneExport } from 'scenes/sceneTypes'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import { InsightShortId } from '~/types'

interface InsightItemPeekProps {
    shortId: InsightShortId
}

/**
 * The insight as the item peek drawer shows it. The insight scene reads its insight from the URL through a
 * single unkeyed logic, so the drawer renders the saved insight read-only instead of a second scene.
 */
export function InsightItemPeek({ shortId }: InsightItemPeekProps): JSX.Element {
    return <Query query={{ kind: NodeKind.SavedInsightNode, shortId }} readOnly embedded />
}

export const scene: SceneExport<InsightItemPeekProps> = {
    component: InsightItemPeek,
    paramsToProps: ({ params: { shortId } }) => ({ shortId: shortId as InsightShortId }),
}
