import { IconTrash } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'logs-drop-rule'

interface LogsSamplingDetailSceneMenuBarProps {
    onDelete: () => void
}

export function LogsSamplingDetailSceneMenuBar(props: LogsSamplingDetailSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <LogsSamplingDetailSceneMenuBarInner {...props} /> : null
}

function LogsSamplingDetailSceneMenuBarInner({ onDelete }: LogsSamplingDetailSceneMenuBarProps): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'delete',
            id: `${RESOURCE_TYPE}-menubar-delete`,
            label: 'Delete drop rule',
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
