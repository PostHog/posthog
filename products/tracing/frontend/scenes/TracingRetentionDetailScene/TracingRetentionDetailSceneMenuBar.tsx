import { IconTrash } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'tracing-retention-rule'

interface TracingRetentionDetailSceneMenuBarProps {
    onDelete: () => void
}

export function TracingRetentionDetailSceneMenuBar(props: TracingRetentionDetailSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <TracingRetentionDetailSceneMenuBarInner {...props} /> : null
}

function TracingRetentionDetailSceneMenuBarInner({ onDelete }: TracingRetentionDetailSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'delete',
            id: `${RESOURCE_TYPE}-menubar-delete`,
            label: 'Delete retention rule',
            icon: <IconTrash />,
            destructive: true,
            onSelect: onDelete,
            pinned: {
                order: 1,
                variant: 'secondary',
                render: () => (
                    <Button variant="destructive-outline" onClick={onDelete}>
                        Delete
                    </Button>
                ),
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
