import { router } from 'kea-router'

import { IconPencil } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'streamlit-app'

export function StreamlitAppSceneMenuBar({ shortId }: { shortId: string }): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <StreamlitAppSceneMenuBarInner shortId={shortId} /> : null
}

function StreamlitAppSceneMenuBarInner({ shortId }: { shortId: string }): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'edit',
            id: `${RESOURCE_TYPE}-menubar-edit`,
            label: 'Edit',
            icon: <IconPencil />,
            onSelect: () => router.actions.push(urls.streamlitAppEdit(shortId)),
            pinned: { order: 1, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
