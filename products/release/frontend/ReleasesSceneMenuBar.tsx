import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { releaseLogic } from './releaseLogic'

const RESOURCE_TYPE = 'releases'

/** The release list and the release calendar share one action list. */
export function ReleasesSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ReleasesSceneMenuBarInner /> : null
}

function ReleasesSceneMenuBarInner(): JSX.Element {
    const { canEditReleases } = useValues(releaseLogic)
    const { setNewReleaseOpen } = useActions(releaseLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-release`,
            label: 'New release',
            icon: <IconPlus />,
            opensFloatingUi: true,
            disabledReason: canEditReleases
                ? undefined
                : 'You need editor access to feature flags to create a release.',
            onSelect: () => setNewReleaseOpen(true),
            // pinned: data-attr values are wire strings
            pinned: { order: 1, variant: 'primary', dataAttr: 'release-new' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
