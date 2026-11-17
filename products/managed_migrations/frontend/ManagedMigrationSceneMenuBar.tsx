import { useActions, useValues } from 'kea'

import { IconUpload } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { managedMigrationLogic } from './managedMigrationLogic'

const RESOURCE_TYPE = 'managed-migration'

export function ManagedMigrationSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ManagedMigrationSceneMenuBarInner /> : null
}

function ManagedMigrationSceneMenuBarInner(): JSX.Element {
    const { managedMigration, isManagedMigrationSubmitting } = useValues(managedMigrationLogic)
    const { submitManagedMigration } = useActions(managedMigrationLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'save',
            id: `${RESOURCE_TYPE}-menubar-submit`,
            label: managedMigration.is_trial ? 'Start trial run' : 'Import data',
            icon: <IconUpload />,
            disabledReason: isManagedMigrationSubmitting ? 'Starting the migration' : undefined,
            onSelect: submitManagedMigration,
            pinned: { order: 1, variant: 'primary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
