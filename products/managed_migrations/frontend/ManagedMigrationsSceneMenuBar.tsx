import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'managed-migrations'

export function ManagedMigrationsSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ManagedMigrationsSceneMenuBarInner /> : null
}

function ManagedMigrationsSceneMenuBarInner(): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-migration`,
            label: 'New migration',
            icon: <IconPlusSmall />,
            onSelect: () => router.actions.push(urls.managedMigrationNew()),
            pinned: { order: 1, variant: 'primary', dataAttr: 'new-managed-migration' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
