import { router } from 'kea-router'

import { IconGear, IconPeople } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'feature-flags-staff-tools'

export function FeatureFlagsStaffToolsSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <FeatureFlagsStaffToolsSceneMenuBarInner /> : null
}

function FeatureFlagsStaffToolsSceneMenuBarInner(): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-cohorts-staff-tools`,
            label: 'Cohorts staff tools',
            icon: <IconPeople />,
            onSelect: () => router.actions.push(urls.cohortsStaffTools()),
            pinned: { order: 1, variant: 'secondary' },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-instance-settings`,
            label: 'Flags-related instance settings',
            icon: <IconGear />,
            onSelect: () => router.actions.push(urls.instanceSettings()),
            pinned: { order: 2, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
