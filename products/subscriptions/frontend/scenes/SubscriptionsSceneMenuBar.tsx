import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'subscriptions'

export function SubscriptionsSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <SubscriptionsSceneMenuBarInner />
}

function SubscriptionsSceneMenuBarInner(): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-subscription`,
            label: 'New subscription',
            icon: <IconPlusSmall />,
            onSelect: () => router.actions.push(urls.subscriptionNew()),
            // pinned: data-attr values are wire strings
            pinned: { order: 0, variant: 'primary', dataAttr: 'new-subscription-button' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
