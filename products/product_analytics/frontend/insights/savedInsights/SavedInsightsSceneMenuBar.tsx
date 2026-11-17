import { IconPlusSmall } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { useHomeDashboardActions } from 'products/product_analytics/frontend/insights/home/useHomeDashboardActions'
import {
    NewInsightButton,
    NewInsightMenuContent,
} from 'products/product_analytics/frontend/insights/newInsightMenu/NewInsightMenu'

const RESOURCE_TYPE = 'saved-insights'

interface SavedInsightsSceneMenuBarProps {
    /** True on the Home tab, where the home dashboard can be customized. */
    isHomeTab: boolean
}

export function SavedInsightsSceneMenuBar(props: SavedInsightsSceneMenuBarProps): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <SavedInsightsSceneMenuBarInner {...props} />
}

function SavedInsightsSceneMenuBarInner({ isHomeTab }: SavedInsightsSceneMenuBarProps): JSX.Element {
    const homeDashboardActions = useHomeDashboardActions(RESOURCE_TYPE)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            type: 'panel',
            id: `${RESOURCE_TYPE}-menubar-new-insight`,
            label: 'New insight',
            icon: <IconPlusSmall />,
            disabledReason:
                getAccessControlDisabledReason(AccessControlResourceType.Insight, AccessControlLevel.Editor) ??
                undefined,
            render: () => <NewInsightMenuContent />,
            panelClassName: 'w-[58rem] max-w-[calc(100vw-1rem)] overflow-y-auto p-4 max-h-[calc(100vh-10rem)]',
            pinned: {
                order: 0,
                variant: 'primary',
                // pinned: data-attr values are wire strings
                dataAttr: 'saved-insights-new-insight-button',
                render: () => <NewInsightButton compact={isHomeTab} />,
            },
        },
        ...(isHomeTab ? homeDashboardActions : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
