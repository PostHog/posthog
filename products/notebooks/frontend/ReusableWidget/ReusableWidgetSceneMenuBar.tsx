import { useActions } from 'kea'

import { IconCode, IconDatabase } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { reusableWidgetLogic } from './reusableWidgetLogic'

const RESOURCE_TYPE = 'reusable-widget'

export function ReusableWidgetSceneMenuBar({ widgetId }: { widgetId: string }): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <ReusableWidgetSceneMenuBarInner widgetId={widgetId} />
}

function ReusableWidgetSceneMenuBarInner({ widgetId }: { widgetId: string }): JSX.Element {
    const { openDemoDataModal, openSourceModal } = useActions(reusableWidgetLogic({ widgetId }))

    const actions: SceneAction[] = [
        {
            group: 'edit',
            section: 'data',
            id: `${RESOURCE_TYPE}-menubar-demo-data`,
            label: 'Demo data',
            icon: <IconDatabase />,
            opensFloatingUi: true,
            onSelect: () => openDemoDataModal(),
            // pinned: data-attr values are wire strings
            pinned: { order: 0, variant: 'secondary', dataAttr: 'reusable-widget-demo-data' },
        },
        {
            group: 'view',
            section: 'source',
            id: `${RESOURCE_TYPE}-menubar-view-source`,
            label: 'View source',
            icon: <IconCode />,
            opensFloatingUi: true,
            onSelect: () => openSourceModal(),
            pinned: { order: 1, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
